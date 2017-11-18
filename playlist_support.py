# -*- coding: utf-8 -*-
import re


from bs4 import BeautifulSoup
from vk_api.audio_url_decoder import decode_audio_url

def found_playlist(link):
	return re.findall(r'(audio_playlist.\d+_\d+)+[/|%2F]*(\w+)*',link)

def get_playlist(api,playlist):
	if not playlist[1]:
		return api.http.get('https://m.vk.com/audio',params={'act':playlist[0]})
	else:
		return api.http.get('https://m.vk.com/audio',params={'act':playlist[0],'access_hash':playlist[1]})

def scrap_data_playlist(html):
	soup = BeautifulSoup(html, 'html.parser')
	tracks = []

	for audio in soup.find_all('div', {'class': 'ai_body'}):
		link = audio.input['value']

		if 'audio_api_unavailable' in link:
			link = decode_audio_url(link)

		tracks.append({
			'artist':audio.select('.ai_artist')[0].text,
			'title':audio.select('.ai_title')[0].text,
			'dur':int(audio.select('.ai_dur')[0]['data-dur']),
			'url':link
		})
	return tracks