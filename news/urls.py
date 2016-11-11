from django.conf.urls import *
from news.models import Post
from django.views.generic.dates import DateDetailView
from news.views import NewsList, YearNews, MonthNews

urlpatterns = [ 
     url(r'^(?P<year>[0-9]{4})/(?P<month>[-\w]+)/(?P<day>[0-9]+)/(?P<slug>[-\w]+)/$',
        DateDetailView.as_view(model=Post, date_field="publish", template_name="news/post_detail.html"),
        name='news_detail'),

    #  url(r'^(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})/$',
    #      view=news_views.post_archive_day,
    #      name='news_archive_day'),
    # 
    #  url(r'^(?P<year>\d{4})/(?P<month>\d{1,2})/$',
    #      view=news_views.post_archive_month,
    #      name='news_archive_month'),
    # 
      url(r'^(?P<year>\d{4})/(?P<month>[-\w]+)/$',
          MonthNews.as_view(date_field="publish"),
          name='news_archive_month'),

      url(r'^(?P<year>\d{4})/$',
          YearNews.as_view(),
          name='news_archive_year'),
    # 
    # # url(r'^categories/(?P<slug>[-\w]+)/$',
    # #     view=news_views.category_detail,
    # #     name='news_category_detail'),
    # #
    # # url (r'^categories/$',
    # #     view=news_views.category_list,
    # #     name='news_category_list'),
    # 
    # url(r'^page/(?P<page>\w)/$',
    #     ListView.as_view(model=Post, template_name="news/post_list.html"),
    #     name='news_index_paginated'),
     
     url(r'^$',
         NewsList.as_view(),
         name='news_index'),
]
