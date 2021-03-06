#!/usr/bin/env python -tt
# encoding: utf-8
#

from .forms import UploadMapForm, EditCommentForm
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, HttpResponseNotAllowed, HttpResponse, HttpResponseBadRequest
from django.urls import reverse
from django.conf import settings
from . import models

from mainpage.wl_utils import get_real_ip
import os


#########
# Views #
#########
def index(request):
    maps = models.Map.objects.all()
    return render(request, 'wlmaps/index.html',
                              {'maps': maps,
                               'maps_per_page': settings.MAPS_PER_PAGE,
                               })


def download(request, map_slug):
    """Very simple view that just returns the binary data of this map and
    increases the download count."""
    m = get_object_or_404(models.Map, slug=map_slug)

    file = open(m.file.path, 'rb')
    data = file.read()
    filename = os.path.basename('%s.wmf' % m.name)

    # Remember that this has been downloaded
    m.nr_downloads += 1
    m.save(update_fields=['nr_downloads'])

    response = HttpResponse(data, content_type='application/octet-stream')
    response['Content-Disposition'] = 'attachment; filename="%s"' % filename

    return response


def view(request, map_slug):
    map = get_object_or_404(models.Map, slug=map_slug)
    context = {
        'map': map,
    }
    return render(request, 'wlmaps/map_detail.html',
                              context)


@login_required
def edit_comment(request, map_slug):
    map = get_object_or_404(models.Map, slug=map_slug)
    if request.method == 'POST':
        form = EditCommentForm(request.POST)
        if form.is_valid():
            map.uploader_comment = form.cleaned_data['uploader_comment']
            map.save(update_fields=['uploader_comment'])
            return HttpResponseRedirect(map.get_absolute_url())
    else:
        form = EditCommentForm(instance=map)

    context = {'form': form, 'map': map}

    return render(request, 'wlmaps/edit_comment.html',
                              context)


@login_required
def upload(request):
    if request.method == 'POST':
        form = UploadMapForm(request.POST, request.FILES)
        if form.is_valid():
            map = form.save(commit=False)
            map.uploader = request.user
            map.save()
            return HttpResponseRedirect(map.get_absolute_url())
    else:
        form = UploadMapForm()

    context = {'form': form, }
    return render(request, 'wlmaps/upload.html',
                              context)
