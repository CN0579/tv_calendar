import datetime
import os
import typing
import random
import time
from typing import Dict, Any

from moviebotapi.common import MenuItem
from moviebotapi.core.models import MediaType
from moviebotapi.subscribe import SubStatus, Subscribe
from moviebotapi.site import Site

import shutil
from mbot.openapi import mbot_api
from mbot.core.plugins import *

import logging
from flask import Blueprint, request

from mbot.common.flaskutils import api_result
from mbot.core.plugins import plugin
from mbot.register.controller_register import login_required
import requests
import bs4

bp = Blueprint('plugin_tv_calendar', __name__)
"""
把flask blueprint注册到容器
这个URL访问完整的前缀是 /api/plugins/你设置的前缀
"""
plugin.register_blueprint('tv_calendar', bp)

server = mbot_api
api_url = "/3/tv/%(tv_id)s/season/%(season_number)s"
tv_api_url = "/3/tv/%(tv_id)s"
param = {'language': 'zh-CN'}
_LOGGER = logging.getLogger(__name__)
message_to_uid: typing.List[int] = []
media_server_enable = False
banner_enable = False
offset = 7
title = '今日剧集已更新 共{tv_total}部'
content = '{tv_name} 第{season}季 第{episodes}集'


@plugin.after_setup
def after_setup(plugin_meta: PluginMeta, config: Dict[str, Any]):
    global message_to_uid
    global media_server_enable
    global banner_enable
    global offset
    global title
    global content
    message_to_uid = config.get('uid') if config.get('uid') else message_to_uid
    media_server_enable = config.get('media_server_enable')
    banner_enable = config.get('banner_enable')
    offset = int(config.get('offset')) if config.get('offset') else offset
    title = config.get('title') if config.get('title') else title
    content = config.get('content') if config.get('content') else content
    shutil.copy('/data/plugins/tv_calendar/frontend/tv_calendar.html', '/app/frontend/static')
    shutil.copy('/data/plugins/tv_calendar/frontend/episode.html', '/app/frontend/static')
    if not os.path.exists('/app/frontend/static/bg.png'):
        shutil.copy('/data/plugins/tv_calendar/frontend/bg.png', '/app/frontend/static')
    """授权并添加菜单"""
    href = '/common/view?hidePadding=true#/static/tv_calendar.html'
    # 授权管理员和普通用户可访问
    server.auth.add_permission([1, 2], href)
    server.auth.add_permission([1, 2], '/api/plugins/tv_calendar/list')
    server.auth.add_permission([1, 2], '/api/plugins/tv_calendar/one')
    server.auth.add_permission([1, 2], '/api/plugins/tv_calendar/choose')
    # 获取菜单，把追剧日历添加到"我的"菜单分组
    menus = server.common.list_menus()
    for item in menus:
        if item.title == '我的':
            test = MenuItem()
            test.title = '追剧日历'
            test.href = href
            test.icon = 'Today'
            item.pages.append(test)
            break
    server.common.save_menus(menus)
    episode_arr = get_calendar_cache()
    if not episode_arr:
        episode_arr = []
        save_calendar_cache(episode_arr)


@plugin.config_changed
def config_changed(config: Dict[str, Any]):
    global message_to_uid
    global media_server_enable
    global banner_enable
    global offset
    global title
    global content
    message_to_uid = config.get('uid') if config.get('uid') else message_to_uid
    media_server_enable = config.get('media_server_enable')
    banner_enable = config.get('banner_enable')
    offset = int(config.get('offset')) if config.get('offset') else offset
    title = config.get('title') if config.get('title') else title
    content = config.get('content') if config.get('content') else content


@plugin.on_event(
    bind_event=['SubMedia'], order=1)
def on_subscribe_new_media(ctx: PluginContext, event_type: str, data: Dict):
    media_type = data['type']
    if media_type == 'TV':
        tmdb_id = data['tmdb_id']
        season_index = data['season_index']
        _LOGGER.info('订阅了新的剧集,开始更新日历数据')
        if tmdb_id and season_index:
            tv = get_tv_info(tmdb_id)
            season = get_tmdb_info(tmdb_id, season_index)
            if tv and season:
                episode_arr = get_calendar_cache()
                tv_poster = tv['poster_path']
                seasons = tv['seasons']
                tv_name = tv['name']
                tv_original_name = tv['original_name']
                backdrop_path = tv['backdrop_path']
                season_poster = find_season_poster(seasons, season_index)
                episodes = season['episodes']
                for episode in episodes:
                    episode['tv_name'] = tv_name
                    episode['tv_original_name'] = tv_original_name
                    episode['tv_poster'] = tv_poster
                    episode['season_poster'] = season_poster
                    episode['backdrop_path'] = backdrop_path
                    episode_arr.append(episode)
                save_calendar_cache(episode_arr)
            else:
                _LOGGER.info('没有查询到tmdb数据')
        _LOGGER.info('更新日历数据完成')


@plugin.task('tv_calendar_save_json', '剧集更新', cron_expression='10 0 * * *')
def task():
    # 怕并发太高，衣总服务器撑不住
    time.sleep(random.randint(1, 3600))
    save_json()


@plugin.task('tv_calendar_save_json', '剧集更新', cron_expression='10 0 * * *')
def task():
    # 怕并发太高，衣总服务器撑不住
    time.sleep(random.randint(1, 3600))
    save_json()


@plugin.task('change_banner', '更新banner', cron_expression='0 11 * * *')
def change_banner_task():
    change_banner()


@bp.route('/list', methods=["GET"])
@login_required()
def get_subscribe_tv_list():
    json_list = get_calendar_cache()
    index_date = get_after_day(datetime.date.today(), -1)
    end_date = get_after_day(index_date, offset - 1)
    index_date_timestamp = int(index_date.strftime('%Y%m%d'))
    end_date_timestamp = int(end_date.strftime('%Y%m%d'))
    filter_list = list(
        filter(lambda x: index_date_timestamp <= get_date_timestamp(x['air_date']) <= end_date_timestamp, json_list)
    )
    episode_list = {}
    result = []
    for item in filter_list:
        tmdb_id = item['show_id']
        season_number = item['season_number']
        season = list(
            filter(lambda x: x['show_id'] == int(tmdb_id) and x['season_number'] == int(season_number), json_list))
        if media_server_enable:
            item['episode_total'] = len(season)
            key = 'key_' + str(tmdb_id) + '_' + str(season_number)
            if key not in episode_list:
                try:
                    episode_arr = get_episode_from_media_server(tmdb_id, season_number)
                    item['episode_arr'] = episode_arr
                    episode_list[key] = episode_arr
                except Exception as e:
                    item['episode_arr'] = []
                    episode_list[key] = []
            else:
                item['episode_arr'] = episode_list[key]
        else:
            item['episode_arr'] = []
        result.append(item)
    return api_result(code=0, message='ok', data=result)


@bp.route('/one', methods=["GET"])
@login_required()
def get_tv_air_date():
    data = request.args
    tmdb_id = data.get('tmdb_id')
    season_number = data.get('season_number')
    json_list = get_calendar_cache()
    filter_list = list(
        filter(lambda x: x['show_id'] == int(tmdb_id) and x['season_number'] == int(season_number), json_list))
    if media_server_enable:
        try:
            episode_arr = get_episode_from_media_server(tmdb_id, season_number)
            filter_list[0]['episode_arr'] = episode_arr
        except Exception as e:
            filter_list[0]['episode_arr'] = []
    else:
        filter_list[0]['episode_arr'] = []
    return api_result(code=0, message='ok', data=filter_list)


@bp.route('/choose', methods=["GET"])
@login_required()
def get_media_server_enable():
    choose = {
        'media_server_enable': media_server_enable,
        'banner_enable': banner_enable
    }
    return api_result(code=0, message='ok', data=choose)


def get_date_timestamp(air_date):
    if air_date == '' or air_date is None:
        return 0
    return int(air_date.replace('-', ''))


def get_tmdb_info(tv_id, season_number):
    return server.tmdb.request_api(api_url % {'tv_id': tv_id, 'season_number': season_number}, param)


def get_after_day(day, n):
    offset = datetime.timedelta(days=n)
    after_day = day + offset
    return after_day


def get_tv_info(tv_id):
    return server.tmdb.request_api(tv_api_url % {'tv_id': tv_id}, param)


def find_season_poster(seasons, season_number):
    for season in seasons:
        if season_number == season['season_number']:
            return season['poster_path']
    return ''


def get_episode_from_media_server(tmdb_id, season_number):
    episode_list = server.media_server.list_episodes_from_tmdb(tmdb_id, season_number)
    episode_number_arr = [int(x.index) for x in episode_list]
    return episode_number_arr


def save_json_no_push():
    _LOGGER.info('开始执行剧集数据更新')
    list_ = server.subscribe.list(MediaType.TV, SubStatus.Subscribing)
    custom_list = server.subscribe.list_custom_sub()
    custom_list_filter = list(filter(lambda x: x.media_type == MediaType.TV and x.tmdb_id and x.enable, custom_list))
    for item in custom_list_filter:
        list_.append(Subscribe({'tmdb_id': item.tmdb_id, 'season_index': item.season_number}, mbot_api.subscribe))
    episode_arr = []
    for row in list_:
        tv = get_tv_info(row.tmdb_id)
        if not tv:
            continue
        tv_poster = tv['poster_path']
        seasons = tv['seasons']
        tv_name = tv['name']
        tv_original_name = tv['original_name']
        backdrop_path = tv['backdrop_path']
        season_poster = find_season_poster(seasons, row.season_number)
        season = get_tmdb_info(row.tmdb_id, row.season_number)
        if not season:
            continue
        episodes = season['episodes']
        for episode in episodes:
            episode['tv_name'] = tv_name
            episode['tv_original_name'] = tv_original_name
            episode['tv_poster'] = tv_poster
            episode['season_poster'] = season_poster
            episode['backdrop_path'] = backdrop_path
            episode_arr.append(episode)

    save_calendar_cache(episode_arr)
    _LOGGER.info('剧集数据更新结束')


def save_json():
    save_json_no_push()
    push_message()


def save_calendar_cache(json_data):
    server.common.set_cache('calendar', 'list', json_data)


def get_calendar_cache():
    json_list = server.common.get_cache('calendar', 'list')
    return json_list


def push_message():
    _LOGGER.info('推送今日更新')
    episode_arr = get_calendar_cache()
    episode_filter = list(
        filter(lambda x: x['air_date'] == datetime.date.today().strftime('%Y-%m-%d'), episode_arr))
    name_dict = {}
    for item in episode_filter:
        if item['tv_name'] not in name_dict:
            name_dict[item['tv_name']] = [item]
        else:
            name_dict[item['tv_name']].append(item)
    img_api = 'https://p.xmoviebot.com/plugins/tv_calendar_logo.jpg'
    tv_total = 0

    message_arr = []
    for tv_name in name_dict:
        tv_total = tv_total + 1
        episodes = name_dict[tv_name]
        episode_number_arr = []
        for episode in episodes:
            episode_number_arr.append(str(episode['episode_number']))
        episode_numbers = ','.join(episode_number_arr)
        qry = {
            'tv_name': tv_name,
            'season': str(episodes[0]['season_number']),
            'episodes': episode_numbers
        }
        message_arr.append(content.format(**qry))
    message = "\n".join(message_arr)

    server_url = mbot_api.config.web.server_url
    if server_url:
        link_url = f"{server_url.rstrip('/')}/common/view?hidePadding=true#/static/tv_calendar.html"
    else:
        link_url = None
    title_qry = {
        'tv_total': tv_total
    }
    title_fmt = title.format(**title_qry)
    if message_to_uid:
        for _ in message_to_uid:
            server.notify.send_message_by_tmpl('{{title}}', '{{a}}', {
                'title': title_fmt,
                'a': message,
                'link_url': link_url,
                'pic_url': img_api
            }, to_uid=_)
    else:
        server.notify.send_message_by_tmpl('{{title}}', '{{a}}', {
            'title': title_fmt,
            'a': message,
            'link_url': link_url,
            'pic_url': img_api
        })
    _LOGGER.info('完成推送')


def change_banner():
    site_list = server.site.list()
    ssd_list = list(
        filter(lambda x: x.site_id == 'ssd', site_list))
    if len(ssd_list) > 0:
        ssd = ssd_list[0]
        cookies = ssd.cookie
        dict_cookie = str_cookies_to_dict(cookies)
        grab_ssd_banner(dict_cookie)
        return True
    else:
        return False


def str_cookies_to_dict(cookies):
    dict_cookie = {}
    str_cookie_list = cookies.split(';')
    for cookie in str_cookie_list:
        if cookie.strip(' '):
            cookie_key_value = cookie.split('=')
            key = cookie_key_value[0]
            value = cookie_key_value[1]
            dict_cookie[key] = value
    return dict_cookie


def grab_ssd_banner(cookies):
    ssd_url = 'https://springsunday.net/index.php'
    resp = requests.get(url=ssd_url, cookies=cookies)
    soup = bs4.BeautifulSoup(resp.text, 'html.parser')
    banner_img_url = soup.select('img.banner-image')[0].get('src')
    save_web_img(banner_img_url, path='/app/frontend/static/bg.png')


def save_web_img(url, path):
    res = requests.get(url)
    with open(path, 'wb') as banner_img:
        banner_img.write(res.content)
