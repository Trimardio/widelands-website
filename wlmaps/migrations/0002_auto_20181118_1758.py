# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2018-11-18 17:58
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wlmaps', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='map',
            name='rating_score',
        ),
        migrations.RemoveField(
            model_name='map',
            name='rating_votes',
        ),
    ]
