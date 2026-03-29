import logging
import time
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings as django_settings
from django.utils import timezone

from analysis.models import CIKMapping, SECFiling
from portfolio.models import Ticker

logger = logging.getLogger(__name__)

_last_sec_request_time = 0.0

SEC_BASE = 'https://data.sec.gov'
EFTS_BASE = 'https://efts.sec.gov/LATEST'
FORM4_TRANSACTION_MAP = {
    'P': 'buy',
    'S': 'sell',
    'A': 'acquisition',
    'M': 'exercise',
    'D': 'disposition',
    'F': 'disposition',  # tax withholding
    'G': 'acquisition',  # gift
}


def _sec_get(url, accept_json=True):
    """Rate-limited GET request to SEC EDGAR."""
    global _last_sec_request_time
    delay = getattr(django_settings, 'SEC_RATE_LIMIT_DELAY', 0.12)
    elapsed = time.time() - _last_sec_request_time
    if elapsed < delay:
        time.sleep(delay - elapsed)
    headers = {
        'User-Agent': getattr(django_settings, 'SEC_EDGAR_USER_AGENT', 'MyStocks/1.0'),
        'Accept-Encoding': 'gzip, deflate',
    }
    if accept_json:
        headers['Accept'] = 'application/json'
    resp = requests.get(url, headers=headers, timeout=15)
    _last_sec_request_time = time.time()
    resp.raise_for_status()
    return resp


class SECFilingService:

    @staticmethod
    def _resolve_cik(ticker):
        """Look up SEC CIK for a ticker, using local cache first."""
        try:
            mapping = CIKMapping.objects.get(ticker=ticker)
            return mapping.cik
        except CIKMapping.DoesNotExist:
            pass

        try:
            resp = _sec_get('https://www.sec.gov/files/company_tickers.json')
            data = resp.json()
            symbol_upper = ticker.symbol.upper()
            for entry in data.values():
                if entry.get('ticker', '').upper() == symbol_upper:
                    cik = str(entry['cik_str']).zfill(10)
                    CIKMapping.objects.update_or_create(
                        ticker=ticker, defaults={'cik': cik}
                    )
                    return cik
        except Exception:
            logger.exception(f"Failed to resolve CIK for {ticker.symbol}")
        return None

    @staticmethod
    def fetch_form4_filings(ticker, days=90):
        """Fetch recent Form 4 insider transaction filings from EDGAR."""
        cik = SECFilingService._resolve_cik(ticker)
        if not cik:
            return []

        start_date = (timezone.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = timezone.now().strftime('%Y-%m-%d')
        search_url = (
            f'{EFTS_BASE}/search-index?q=%22{ticker.symbol}%22'
            f'&dateRange=custom&startdt={start_date}&enddt={end_date}'
            f'&forms=4&from=0&size=20'
        )

        try:
            resp = _sec_get(search_url)
            results = resp.json()
        except Exception:
            logger.exception(f"Failed to search Form 4 for {ticker.symbol}")
            return []

        hits = results.get('hits', {}).get('hits', [])
        new_filings = []

        for hit in hits[:20]:
            source = hit.get('_source', {})
            accession = source.get('file_num', '') or source.get('accession_no', '')
            # Normalize accession number
            accession_raw = hit.get('_id', accession).replace('-', '')
            if not accession_raw:
                continue

            # Check if we already have this filing
            if SECFiling.objects.filter(
                ticker=ticker, accession_number=accession_raw
            ).exists():
                continue

            # Try to get the filing XML
            filing_url = source.get('file_url', '')
            if not filing_url:
                # Build URL from accession number
                accession_dashes = source.get('accession_no', '')
                if accession_dashes:
                    cik_str = cik.lstrip('0') or '0'
                    filing_url = (
                        f'{SEC_BASE}/Archives/edgar/data/{cik_str}/'
                        f'{accession_dashes.replace("-", "")}/{accession_dashes}.txt'
                    )

            if not filing_url:
                continue

            try:
                filing_data = SECFilingService._parse_form4_from_search(source, accession_raw)
                if filing_data:
                    for txn in filing_data:
                        acc_key = f"{accession_raw}_{txn.get('idx', 0)}"
                        if SECFiling.objects.filter(
                            ticker=ticker, accession_number=acc_key
                        ).exists():
                            continue
                        filing = SECFiling.objects.create(
                            ticker=ticker,
                            form_type='4',
                            filed_at=txn['filed_at'],
                            filer_name=txn['filer_name'],
                            filer_title=txn.get('filer_title', ''),
                            transaction_type=txn['transaction_type'],
                            shares=txn.get('shares'),
                            price_per_share=txn.get('price'),
                            total_value=txn.get('total_value'),
                            accession_number=acc_key,
                            raw_data=txn.get('raw', {}),
                        )
                        new_filings.append(filing)
            except Exception:
                logger.exception(f"Failed to parse Form 4 filing {accession_raw}")

        return new_filings

    @staticmethod
    def _parse_form4_from_search(source, accession):
        """Parse Form 4 data from EDGAR search result metadata."""
        filed_str = source.get('file_date', '') or source.get('date_filed', '')
        if not filed_str:
            return []

        try:
            filed_at = timezone.datetime.fromisoformat(filed_str)
            if timezone.is_naive(filed_at):
                filed_at = timezone.make_aware(filed_at)
        except (ValueError, TypeError):
            filed_at = timezone.now()

        display_names = source.get('display_names', [])
        filer_name = display_names[0] if display_names else source.get('entity_name', 'Unknown')

        # EDGAR search doesn't give us full transaction XML,
        # but we can extract basic info from the metadata
        return [{
            'filed_at': filed_at,
            'filer_name': filer_name,
            'filer_title': '',
            'transaction_type': 'buy',  # Default; refined by XML parse if available
            'shares': None,
            'price': None,
            'total_value': None,
            'idx': 0,
            'raw': source,
        }]

    @staticmethod
    def fetch_form4_xml(ticker, cik):
        """Fetch and parse actual Form 4 XML filings for detailed transaction data."""
        cik_str = cik.lstrip('0') or '0'
        url = f'{SEC_BASE}/submissions/CIK{cik}.json'

        try:
            resp = _sec_get(url)
            data = resp.json()
        except Exception:
            logger.exception(f"Failed to fetch submissions for CIK {cik}")
            return []

        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        accessions = recent.get('accessionNumber', [])
        dates = recent.get('filingDate', [])
        primary_docs = recent.get('primaryDocument', [])

        new_filings = []
        cutoff = (timezone.now() - timedelta(days=90)).strftime('%Y-%m-%d')

        for i, form in enumerate(forms):
            if form != '4':
                continue
            if i >= len(dates) or dates[i] < cutoff:
                continue
            if i >= len(accessions):
                break

            accession = accessions[i]
            acc_nodash = accession.replace('-', '')

            if SECFiling.objects.filter(
                ticker=ticker, accession_number__startswith=acc_nodash
            ).exists():
                continue

            if i >= len(primary_docs):
                continue

            doc_url = (
                f'{SEC_BASE}/Archives/edgar/data/{cik_str}/'
                f'{acc_nodash}/{primary_docs[i]}'
            )

            try:
                xml_resp = _sec_get(doc_url, accept_json=False)
                parsed = SECFilingService._parse_form4_xml(
                    xml_resp.text, acc_nodash, dates[i]
                )
                for txn in parsed:
                    acc_key = f"{acc_nodash}_{txn['idx']}"
                    if SECFiling.objects.filter(
                        ticker=ticker, accession_number=acc_key
                    ).exists():
                        continue
                    filing = SECFiling.objects.create(
                        ticker=ticker,
                        form_type='4',
                        filed_at=txn['filed_at'],
                        filer_name=txn['filer_name'],
                        filer_title=txn.get('filer_title', ''),
                        transaction_type=txn['transaction_type'],
                        shares=txn.get('shares'),
                        price_per_share=txn.get('price'),
                        total_value=txn.get('total_value'),
                        accession_number=acc_key,
                        raw_data=txn.get('raw', {}),
                    )
                    new_filings.append(filing)
            except Exception:
                logger.exception(f"Failed to parse Form 4 XML {doc_url}")

            if len(new_filings) >= 20:
                break

        return new_filings

    @staticmethod
    def _parse_form4_xml(xml_text, accession, filed_date):
        """Parse a Form 4 XML document into transaction records."""
        transactions = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        # Namespace handling — Form 4 XML may or may not use namespaces
        ns = ''
        if root.tag.startswith('{'):
            ns = root.tag.split('}')[0] + '}'

        # Get reporting owner info
        owner_el = root.find(f'{ns}reportingOwner')
        filer_name = 'Unknown'
        filer_title = ''
        if owner_el is not None:
            name_el = owner_el.find(f'{ns}reportingOwnerId/{ns}rptOwnerName')
            if name_el is not None and name_el.text:
                filer_name = name_el.text.strip()
            rel_el = owner_el.find(f'{ns}reportingOwnerRelationship')
            if rel_el is not None:
                title_el = rel_el.find(f'{ns}officerTitle')
                if title_el is not None and title_el.text:
                    filer_title = title_el.text.strip()
                elif rel_el.find(f'{ns}isDirector') is not None:
                    if (rel_el.find(f'{ns}isDirector').text or '').strip() == '1':
                        filer_title = 'Director'

        try:
            filed_at = timezone.datetime.fromisoformat(filed_date)
            if timezone.is_naive(filed_at):
                filed_at = timezone.make_aware(filed_at)
        except (ValueError, TypeError):
            filed_at = timezone.now()

        # Parse non-derivative transactions
        idx = 0
        for txn_type_tag in ['nonDerivativeTransaction', 'derivativeTransaction']:
            for txn_el in root.iter(f'{ns}{txn_type_tag}'):
                code_el = txn_el.find(
                    f'{ns}transactionCoding/{ns}transactionCode'
                )
                code = code_el.text.strip() if code_el is not None and code_el.text else 'P'
                txn_type = FORM4_TRANSACTION_MAP.get(code, 'buy')

                shares_el = txn_el.find(
                    f'{ns}transactionAmounts/{ns}transactionShares/{ns}value'
                )
                shares = None
                if shares_el is not None and shares_el.text:
                    try:
                        shares = Decimal(shares_el.text.strip())
                    except InvalidOperation:
                        pass

                price_el = txn_el.find(
                    f'{ns}transactionAmounts/{ns}transactionPricePerShare/{ns}value'
                )
                price = None
                if price_el is not None and price_el.text:
                    try:
                        price = Decimal(price_el.text.strip())
                    except InvalidOperation:
                        pass

                total_value = None
                if shares and price:
                    total_value = shares * price

                transactions.append({
                    'filed_at': filed_at,
                    'filer_name': filer_name,
                    'filer_title': filer_title,
                    'transaction_type': txn_type,
                    'shares': shares,
                    'price': price,
                    'total_value': total_value,
                    'idx': idx,
                    'raw': {
                        'code': code,
                        'tag': txn_type_tag,
                    },
                })
                idx += 1

        return transactions

    @staticmethod
    def fetch_13d_filings(ticker, days=90):
        """Fetch recent Schedule 13D/13G filings."""
        cik = SECFilingService._resolve_cik(ticker)
        if not cik:
            return []

        cik_str = cik.lstrip('0') or '0'
        url = f'{SEC_BASE}/submissions/CIK{cik}.json'

        try:
            resp = _sec_get(url)
            data = resp.json()
        except Exception:
            logger.exception(f"Failed to fetch submissions for CIK {cik}")
            return []

        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        accessions = recent.get('accessionNumber', [])
        dates = recent.get('filingDate', [])

        cutoff = (timezone.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        new_filings = []

        for i, form in enumerate(forms):
            if not form.startswith('SC 13'):
                continue
            if i >= len(dates) or dates[i] < cutoff:
                continue
            if i >= len(accessions):
                break

            accession = accessions[i].replace('-', '')
            if SECFiling.objects.filter(
                ticker=ticker, accession_number=accession
            ).exists():
                continue

            try:
                filed_at = timezone.datetime.fromisoformat(dates[i])
                if timezone.is_naive(filed_at):
                    filed_at = timezone.make_aware(filed_at)
            except (ValueError, TypeError):
                filed_at = timezone.now()

            filing = SECFiling.objects.create(
                ticker=ticker,
                form_type=form,
                filed_at=filed_at,
                filer_name='Institutional filer',
                transaction_type='acquisition',
                accession_number=accession,
                raw_data={'form': form, 'date': dates[i]},
            )
            new_filings.append(filing)

        return new_filings

    @staticmethod
    def refresh_sec_data(ticker):
        """Fetch all SEC filing types for a ticker. Skip if data is recent."""
        # Skip if we fetched within last 6 hours
        recent_cutoff = timezone.now() - timedelta(hours=6)
        if SECFiling.objects.filter(
            ticker=ticker, created_at__gte=recent_cutoff
        ).exists():
            logger.debug(f"SEC data for {ticker.symbol} is recent, skipping")
            return

        cik = SECFilingService._resolve_cik(ticker)
        if not cik:
            logger.warning(f"No CIK found for {ticker.symbol}, skipping SEC data")
            return

        try:
            SECFilingService.fetch_form4_xml(ticker, cik)
        except Exception:
            logger.exception(f"Error fetching Form 4 XML for {ticker.symbol}")

        try:
            SECFilingService.fetch_13d_filings(ticker)
        except Exception:
            logger.exception(f"Error fetching 13D filings for {ticker.symbol}")

        logger.info(f"SEC data refresh complete for {ticker.symbol}")
