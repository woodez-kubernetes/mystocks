from django.db import migrations, models
import django.db.models.deletion


DEFAULT_FEEDS = [
    {
        'name': 'CNBC Markets',
        'url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069',
        'category': 'stock',
    },
    {
        'name': 'CNBC Economy',
        'url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258',
        'category': 'geopolitical',
    },
    {
        'name': 'MarketWatch Top Stories',
        'url': 'https://feeds.marketwatch.com/marketwatch/topstories/',
        'category': 'stock',
    },
    {
        'name': 'Investing.com News',
        'url': 'https://www.investing.com/rss/news.rss',
        'category': 'stock',
    },
    {
        'name': 'Seeking Alpha Market Currents',
        'url': 'https://seekingalpha.com/market_currents.xml',
        'category': 'stock',
    },
    {
        'name': 'BBC World News',
        'url': 'http://feeds.bbci.co.uk/news/world/rss.xml',
        'category': 'geopolitical',
    },
    {
        'name': 'Al Jazeera',
        'url': 'https://www.aljazeera.com/xml/rss/all.xml',
        'category': 'geopolitical',
    },
]


def deduplicate_urls(apps, schema_editor):
    """Remove duplicate URLs, keeping the first (earliest) entry."""
    NewsArticle = apps.get_model('market', 'NewsArticle')
    from django.db.models import Min
    dupes = (
        NewsArticle.objects.values('url')
        .annotate(min_id=Min('id'), cnt=models.Count('id'))
        .filter(cnt__gt=1)
    )
    for dupe in dupes:
        NewsArticle.objects.filter(url=dupe['url']).exclude(id=dupe['min_id']).delete()


def seed_feeds(apps, schema_editor):
    RSSFeedSource = apps.get_model('market', 'RSSFeedSource')
    for feed in DEFAULT_FEEDS:
        RSSFeedSource.objects.get_or_create(
            url=feed['url'],
            defaults={'name': feed['name'], 'category': feed['category']},
        )


def unseed_feeds(apps, schema_editor):
    RSSFeedSource = apps.get_model('market', 'RSSFeedSource')
    urls = [f['url'] for f in DEFAULT_FEEDS]
    RSSFeedSource.objects.filter(url__in=urls).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('market', '0002_newsarticle'),
        ('portfolio', '0003_watchlistitem'),
    ]

    operations = [
        # 1. Create RSSFeedSource model
        migrations.CreateModel(
            name='RSSFeedSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('url', models.URLField(max_length=500, unique=True)),
                ('category', models.CharField(choices=[('stock', 'Stock/Market'), ('geopolitical', 'Geopolitical')], default='stock', max_length=15)),
                ('enabled', models.BooleanField(default=True)),
                ('last_fetched', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        # 2. Deduplicate URLs before adding unique constraint
        migrations.RunPython(deduplicate_urls, migrations.RunPython.noop),
        # 3. Remove old unique_together
        migrations.AlterUniqueTogether(
            name='newsarticle',
            unique_together=set(),
        ),
        # 4. Make ticker nullable
        migrations.AlterField(
            model_name='newsarticle',
            name='ticker',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='news_articles',
                to='portfolio.ticker',
            ),
        ),
        # 5. Make url unique
        migrations.AlterField(
            model_name='newsarticle',
            name='url',
            field=models.URLField(max_length=1000, unique=True),
        ),
        # 6. Add feed_source FK
        migrations.AddField(
            model_name='newsarticle',
            name='feed_source',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='articles',
                to='market.rssfeedsource',
            ),
        ),
        # 7. Seed default feeds
        migrations.RunPython(seed_feeds, unseed_feeds),
    ]
