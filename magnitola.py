# -*- coding: utf-8 -*-
import traceback
import requests
import re
import gevent
import youtube_dl

from json import loads
import subprocess

from datetime import timedelta as sectohum
from time import time

from disco.bot import Plugin
from disco.bot.command import CommandError
from player import Player
from player_codecs import BufferedOpusEncoderPlayable, FFmpegInput
from disco.voice.client import VoiceException

from vk_api.audio import VkAudio
from vk_api import VkApi

from playlist_support import found_playlist,get_playlist,scrap_data_playlist

class FakeChannel:
	id = 0

class FakeHeader:
	headers = {'Content-Type':'None'}

class DiscordPlugin:
	def __init__(self,dc):
		self.dc = dc
		self.desc = 'magnitola,m,магнитола,м <arg> - voisproizvedenie muziki v golosovoy chat\n'
		self.desc_priory = 'audio'
		api = VkApi('login','pass')
		api.auth()
		self.vkaudio = VkAudio(api)
		self.guilds = {}
		self.search = {}
		print u'magnitola'
		self.ydl = youtube_dl.YoutubeDL()
		self.settings = {}
		self.parse_cmd = u"ffprobe -print_format json -loglevel panic -show_entries stream=codec_name:format -select_streams a:0 -i {}"

	def inactivitycheck(self):
		max_delay_in_voice = 600
		while True:
			gevent.sleep(60)
			for guild_id,voice_id in self.guilds.keys():
				try:
					if not self.get_player((guild_id,voice_id)).already_play and not self.get_player((guild_id,voice_id)).queue._data and (time() - self.get_player((guild_id,voice_id)).last_activity > max_delay_in_voice):
						self.get_player((guild_id,voice_id)).complete.set()
						self.get_player((guild_id,voice_id)).disconnect()
				except Exception as e:
					print e
					pass

	def getmetadata(self,url):
		output = {}
		try:
			response = loads(subprocess.check_output(self.parse_cmd.format(url).split()))
			output.update({'size':int(response['format'].get('size',0))})
			output.update({'duration':int(float(response['format'].get('duration',0)))})
			output.update({'artist':response['format'].get(u'tags',{}).get(u'artist','Unknown Artist')})
			output.update({'title':response['format'].get(u'tags',{}).get(u'title','Unknown Title')})
			return output
		except subprocess.CalledProcessError:
			return output

	def getkeys(self):
		keys = [u'magnitola',u'магнитола',u'm',u'м',u'magnitofon',u'магнитофон']
		plugin_container = {}
		for key in keys:
			plugin_container[key] = self
		return plugin_container

	def get_player(self, id_comb):
		if id_comb not in self.guilds:
			raise CommandError("I'm not currently playing music here.")
		return self.guilds.get(id_comb)

	def call(self,msg):
		if msg['user_id'] in self.settings:
			bass_count = self.settings[msg['user_id']]['bass']
		else:
			self.settings.update({msg['user_id']:{'bass':0}})
			bass_count = 0
		q = None
		use_vk = None
		offset = 0
		helper = """
nu ebat vvedi comandu:
retard magnitola <cmd> <arg>

[j]oin,[з]айди,сюды - chtob zavalitsya v golosovoy chat
[l]eave,[у]йди,съеби - chtoba ya s'ebal iz golosovogo

[p]lay,[п]ро[и]грай,взбрынцай <link> - proigrat govninu po ssile
retard m p http://youtube....
retard m play http://vk.com/audio.....playlist.....audio_playlist270279842_68104179
retard м и http://server.domain/mocha.mp3.....

[н]айди,search,q <request> - naydet i vidas resultati
retard m q retardbot
retard m <track number> - to play

[s]top,[с]топ,хорош - skipnet tekuschiy track
pp,pause,погодь - stavit na pausu
[r]esume,валяй - voisproizvodit track s pausi
[n]ow,[се]йчас - chto sha igraet
[pl]aylist,[пл]ейлист - pokajet ochered

setbass,sb [-50...50] - dobavit bassssssssa!!	
"""

		args = msg['body'].split()
		try:
			command = args[2]
		except:
			return msg['source'].reply(helper)

		if command in [u"setbass",u"sb"]:
			try:
				count = int(args[3])
			except:
				return msg['source'].reply(u"nu ebana vvedi CHISLO... TOEST\nretard m setbass 30")
			if count > 50 or count < -50:
				return msg['source'].reply(u"ti che ebanutiy vvedi chislo ot -50 do 50")
			self.settings[msg['user_id']]['bass'] = count
			return msg['source'].reply('bass setted!\n result listen in next use play command')

		if (msg['source'].guild.id,msg['source'].author.id) in self.search:
			try:
				track_number = int(args[2])
			except:
				try:
					track_number = int(args[3])
				except:
					del self.search[(msg['source'].guild.id,msg['source'].author.id)]
					return self.call(msg)
			command = u"play"
			if track_number > 49:
				offset = self.search[(msg['source'].guild.id,msg['source'].author.id)][1] * 20
				page = self.search[(msg['source'].guild.id,msg['source'].author.id)][1] + 1
				command = 'q'
				q = self.search[(msg['source'].guild.id,msg['source'].author.id)][2]
			else:
				try:
					use_vk = self.search[(msg['source'].guild.id,msg['source'].author.id)][0][track_number]['url']
					title = self.search[(msg['source'].guild.id,msg['source'].author.id)][0][track_number]['title']
					artist = self.search[(msg['source'].guild.id,msg['source'].author.id)][0][track_number]['artist']
					duration = self.search[(msg['source'].guild.id,msg['source'].author.id)][0][track_number]['dur']
				except IndexError:
					return msg['source'].reply(self.dc.markdown.blue(u'kruto trolish.....\n\n dlya 1 klassa\n\n vvedi nomer iz dostupnih debil'))

		voice_channel_id = getattr(msg['source'].guild.get_member(msg['source'].author).get_voice_state(),'channel',FakeChannel).id		

		if command in [u'leave',u'съеби',u'уйди',u'l',u'у']:
			if (msg['source'].guild.id,voice_channel_id) in self.guilds:
				player = self.get_player((msg['source'].guild.id,voice_channel_id))
				if player:
					player.force_kick = True
					player.queue._data = []
					player.disconnect()
					if (msg['source'].guild.id,voice_channel_id) in self.guilds:
						del self.guilds[(msg['source'].guild.id,voice_channel_id)]
					del player
					return msg['source'].reply('pokedova')
				else:
					return msg['source'].reply('nu okeeeeeey?')
			else:
				return msg['source'].reply('y menya v db napisano,chto menya zdes net')

		if command in [u'join',u'зайди',u'сюды',u'j',u'з',u'сюда']:
			if (msg['source'].guild.id,voice_channel_id) in self.guilds:
				return msg['source'].reply('ya uje tut ueba...')

			for gid,vid in self.guilds:
				if gid == msg['source'].guild.id and not vid == voice_channel_id:
					return msg['source'].reply('ya uje est na dannom servere, gdeto v golosovom chate...')
			
			state = msg['source'].guild.get_member(msg['source'].author).get_voice_state()
			if not state:
				return msg['source'].reply('nu epta ti sam v golosovoy chat voydi...')

			try:
				client = state.channel.connect()
			except VoiceException as e:
				return msg['source'].reply('ay blya ne mogu viyti v golosovoy anal, problema: `{}`'.format(e))

			msg['source'].reply('tak zahodim ebana........')
			self.guilds[(msg['source'].guild.id,voice_channel_id)] = Player(client)
			self.guilds[(msg['source'].guild.id,voice_channel_id)].complete.wait()
			if (msg['source'].guild.id,voice_channel_id) in self.guilds and not self.guilds[(msg['source'].guild.id,voice_channel_id)].force_kick:
				msg['source'].reply("ya dau po s'ebam raz uj prosto tak siju i kayfuu zdesya..!")
			if (msg['source'].guild.id,voice_channel_id) in self.guilds:
				del self.guilds[(msg['source'].guild.id,voice_channel_id)]
			return
 
		try:
			if not (msg['source'].guild.id,voice_channel_id) in self.guilds:
				return msg['source'].reply('nujno chtob ya bil v kanale so zvukom i chtob ti tam sam bil')
				
			if command in [u'search',u'найди',u'q',u'н']:
				if not q:
					q = msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:]
				if not q:
					return msg['source'].reply('nu ti zapross vvedi')
				try:
					if not offset:
						page = 1
					print u"page: %s, offset: %s, q: %s" % (page,offset,q)
					response = self.vkaudio.search(q,offset)
				except:
					try:
						response = self.vkaudio.search(q,offset)
					except Exception as e:
						return msg['source'].reply('vk api error\n{}'.format(e))
				if not response:
					return msg['source'].reply('nichego ne nashel')
				text = u'enter:\nretard magnitola <number>\n\nnum duration name:\n'
				for track in response:
					text += u'%02d: %s %s - %s\n' % (response.index(track),sectohum(seconds=int(track['dur'])),track['artist'],track['title'])
					
				self.search[(msg['source'].guild.id,msg['source'].author.id)] = (response,page,q)
				return msg['source'].reply(text[:1999])
	
			if command in [u'play',u'проиграй',u'взбрынцай',u'p',u'и',u'п']:
				if use_vk:
					args = ['retard','m','p',use_vk]
				try:
					url = args[3]
				except:
					return msg['source'].reply('nu ti ssilku ukaji blya')
				try:
					int(url)
					msg['body'] = u'retard m {}'.format(url)
					return self.call(msg)
				except ValueError:
					pass
				if not use_vk:
					try:
						if not (u'.mp3' in url and u'#FILENAME/' in url):
							pre_cache_media = self.getmetadata(url)
							if not pre_cache_media:
								pre_cache = requests.get(url)
							else:
								pre_cache = FakeHeader()
					except IOError:
						msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
						return self.call(msg)
					except UnicodeError:
						msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
						return self.call(msg)

				#print url
				#print found_playlist(url)
				if use_vk:
					#print use_vk
					item = FFmpegInput(use_vk,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = duration,artist = artist,title = title,respond=msg['source'].reply).pipe(BufferedOpusEncoderPlayable)
				elif found_playlist(url):
					try:
						server_response = get_playlist(self.dc.vk,found_playlist(url)[0])
					except:
						try:
							server_response = get_playlist(self.dc.vk,found_playlist(url)[0])
						except:
							return msg['source'].reply(self.dc.markdown.blue(u'vo vremya ppolycheniya playlista proizoshla oshibka...'))

					try:
						tracks = scrap_data_playlist(server_response.text,self.vkaudio.user_id)
					except Exception as e:
						return msg['source'].reply(self.dc.markdown.blue(u'stranica s albomom bila zagrujena, no ya ne smog ee sparsit, prichina etomu oshibka:{}'.format(e)))		
					text = ''
					all_play_time = 0
					accept_tracks = 0
					if not tracks:
						return msg['source'].reply(self.dc.markdown.blue(u'vozmojno danniy playlist yavlyatsya privatnim'))
					counter = 0
					for track in tracks:
						if counter > 29:
							break
						if track['dur'] < 3000:
							text += u'{}: {} {} - {}\n'.format(tracks.index(track),sectohum(seconds=int(track['dur'])),track['artist'],track['title'])
							self.get_player((msg['source'].guild.id,voice_channel_id)).queue.append(FFmpegInput(track['url'],bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = track['dur'],artist=track['artist'],title=track['title'],respond=msg['source'].reply).pipe(BufferedOpusEncoderPlayable))
							all_play_time += int(track['dur'])
							accept_tracks += 1
						else:
							text += u'{}: {} {} - {} - SKIPPED\n'.format(tracks.index(track),sectohum(seconds=int(track['dur'])),track['artist'],track['title'])

					text = u"Duration: {}\nTracks: {}\nPlaylist:\n".format(sectohum(seconds=all_play_time),accept_tracks) + text

					for text_frame in [text[i:i+1980] for i in range(0,len(text),1980)]:
						msg['source'].reply(self.dc.markdown.block(text_frame))
					return
					#return msg['source'].reply(self.dc.markdown.block(text[:1999]))
				elif u'.mp3' in url and u'#FILENAME/' in url:
					msg['body'] = u'retard m p {}'.format(url.split(u'#FILENAME/')[0])
					return self.call(msg)
					#return msg['source'].reply(self.dc.markdown.blue(u'nu ti blya iz konca ssilki uberi #FILENAME/....\n\nponastavite govno pluginov na brauzer i ebetes v jeppu'))
				elif u'.mp3' in url and pre_cache_media and pre_cache_media.get('size',0):
					if pre_cache_media.get('size',0) > 50971520:
						return msg['source'].reply(self.dc.markdown.blue(u'chta tvoya mp3 kakayata bolshaya kak tvoya mamka'))
					elif pre_cache_media.get('size',0) > 8192:
						item = FFmpegInput(url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration=pre_cache_media.get('duration'),artist = pre_cache_media.get('artist'),title=pre_cache_media.get('title'),filesize=pre_cache_media.get('size'),respond=msg['source'].reply).pipe(BufferedOpusEncoderPlayable)
					else:
						return msg['source'].reply(self.dc.markdown.blue(u'chta tvoya mp3 kakayata malenkaya'))
				elif pre_cache.headers.get('Content-Type') == 'audio/mpeg':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#item = FFmpegInput(url).pipe(BufferedOpusEncoderPlayable)
				elif pre_cache.headers.get('Content-Type') == 'audio/x-scpls':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#link = re.findall(r'http+.+\b',pre_cache.read())
					#if link:
					#	item = YoutubeDLInput(link[0]).pipe(BufferedOpusEncoderPlayable)
					#else:
					#	return msg['source'].reply(self.dc.markdown.blue(u'ya opredeliil, chto eto potok audio/x-scpls, tolko ssilku ne smog zaparsit'))
				elif pre_cache.headers.get('Content-Type') == 'video/x-ms-asf':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#link = re.findall(r'http+.+\b',pre_cache.read())
					#if link:
					#	item = YoutubeDLInput(link[0]).pipe(BufferedOpusEncoderPlayable)
					#else:
					#	return msg['source'].reply(self.dc.markdown.blue(u'ya opredeliil, chto eto potok video/x-ms-asf, tolko ssilku ne smog zaparsit'))
				elif pre_cache.headers.get('Content-Type') == 'application/x-mpegurl':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#link = re.findall(r'http+.+\b',pre_cache.read())
					#if link:
					#	item = YoutubeDLInput(link[0]).pipe(BufferedOpusEncoderPlayable)
					#else:
					#	return msg['source'].reply(self.dc.markdown.blue(u'ya opredeliil, chto eto potok application/x-mpegurl, tolko ssilku ne smog zaparsit'))
				elif re.findall(r"(\S+watch\?v=[\w,-]+)|(\S+[\w,-]+)",url):
					if re.findall(r"(\S+watch\?v=[\w,-]+)|(\S+[\w,-]+)",url)[0][0]:
						url = re.findall(r"(\S+watch\?v=[\w,-]+)|(\S+[\w,-]+)",url)[0][0]
					else:
						url = re.findall(r"(\S+watch\?v=[\w,-]+)|(\S+[\w,-]+)",url)[0][1]

					try:
						ytd = self.ydl.extract_info(url, download=False, process=False)
					except:
						return msg['source'].reply(u'Unknown source/// Server return 404///Url: {}'.format(url))

					if not 'duration' in ytd:
						return self.call(u'ta ssilka kotoruu ti kidaesh ne imeet dlitelnosti, a znachit ya ne mogu ee proverit')

					if ytd['duration'] > 36000:
						msg['body'] = u'retard m p https://www.youtube.com/watch?v=tKdcjJoXeEY'
						msg['source'].reply('chto lubitel prodoljovatih predmetov???')
						return self.call(msg)
					if ytd['duration'] > 3500:
						msg['source'].reply('vot skaji vo chesnaku nahuya mne igrat celiy chas??')
						msg['body'] = u'retard m p https://www.youtube.com/watch?v=9sWjFgRN7Vc'
						return self.call(msg)
					if ytd['duration'] > 1800:
						return msg['source'].reply(self.dc.markdown.blue(u'ebaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaat ona dlinnaya kak moy houy...'))
					url = ytd['formats'][0]['url']
					duration = ytd['duration']
					try:
						title = ytd['title']
					except:
						title = u'From YTD'
					try:
						artist = ytd['uploader']
					except:
						artist = u'YTD uploader'
					item = FFmpegInput(url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = duration,artist = artist,title = title,filesize = ytd.get('size',0),respond=msg['source'].reply).pipe(BufferedOpusEncoderPlayable)
				else:
					ytd = self.ydl.extract_info(url, download=False, process=False)
					if not 'duration' in ytd:
						return msg['source'].reply("i kak ya uznau...., chto eto huynya ne ub'et menya.. ya hz skoka ona dlitsya")
					if ytd['duration'] > 1800:
						return msg['source'].reply(self.dc.markdown.blue(u'ebaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaat ona dlinnaya kak moy houy...'))
					url = ytd['formats'][0]['url']
					duration = ytd['duration']
					try:
						title = ytd['title']
					except:
						title = u'From unknown YTD'
					try:
						artist = ytd['uploader']
					except:
						artist = u'YTD unknown uploader'
					item = FFmpegInput(url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = duration,artist = artist,title = title,filesize = ytd.get('size',0),respond=msg['source'].reply).pipe(BufferedOpusEncoderPlayable)
				self.get_player((msg['source'].guild.id,voice_channel_id)).queue.append(item)
				if self.get_player((msg['source'].guild.id,voice_channel_id)).already_play:
					return msg['source'].reply('nu chtoj rvi dushu sanya...\n tvoe mesto v ocheredi, vrode kak: %s' % len(self.guilds[(msg['source'].guild.id,voice_channel_id)].queue))
				else:
					return

			if command in [u'now',u'сейчас',u'n',u'се',u'сe']:
				if (msg['source'].guild.id,voice_channel_id) in self.guilds:
					try:
						current = self.get_player((msg['source'].guild.id,voice_channel_id)).now_playing.source
						current.respond(u"""
Now playing: {} - {}
Played: {}/{}
Request: <@{}>
""".format(current.artist,current.title,sectohum(seconds=int(current.played)),sectohum(seconds=int(current.duration)),current.user_id))
						current = None
						return
					except AttributeError:
						return msg['source'].reply('nihuya net igraet sha, infa sotka')
					#return msg['source'].reply('jdem, poka ti razrodishsya')
				else:
					return msg['source'].reply('tak ya nichego ne igrau')

			if command in [u'playlist',u'плейлист',u'пл',u'pl']:
				if (msg['source'].guild.id,voice_channel_id) in self.guilds:
					try:
						text = u"Playlist:\n"
						if self.get_player((msg['source'].guild.id,voice_channel_id)).queue._data:
							for item in self.get_player((msg['source'].guild.id,voice_channel_id)).queue._data:
								text += u"""
{}: {} - {}, {}
request: <@{}>
""".format(self.get_player((msg['source'].guild.id,voice_channel_id)).queue._data.index(item),item.source.artist,item.source.title, sectohum(seconds=int(item.source.duration)),item.source.user_id)
							return msg['source'].reply(text[:1999])
						else:
							return msg['source'].reply(u"playlist pustoy((")
					except AttributeError:
						return msg['source'].reply('nihuya net igraet sha i ne budet igrat, infa sotka')
				else:
					return msg['source'].reply('tak ya nichego ne igrau i ne budu igrat')
	
			if command in [u'pause',u'погодь',u'pp']:
				if (msg['source'].guild.id,voice_channel_id) in self.guilds:
					try:
						self.get_player((msg['source'].guild.id,voice_channel_id)).pause()
					except AttributeError:
						return msg['source'].reply('nihuya net igraet sha, infa sotka')
					return msg['source'].reply('jdem, poka ti razrodishsya')
				else:
					return msg['source'].reply('tak ya nichego ne igrau')
	
			if command in [u'resume',u'валяй',u'r']:
				if (msg['source'].guild.id,voice_channel_id) in self.guilds:
					try:
						self.get_player((msg['source'].guild.id,voice_channel_id)).resume()
					except AttributeError:
						return msg['source'].reply('nihuya net igraet sha, infa sotka')
					return msg['source'].reply('rvem dushu')
				else:
					return msg['source'].reply('tak ya nichego ne igrau')

			if command in [u'stop',u'стоп',u'стопе',u'хорош',u's',u'с',u'c']:
				if (msg['source'].guild.id,voice_channel_id) in self.guilds:
					try:
						track_nums = int(args[3])
					except:
						track_nums = None

					if True:
						try:
							self.get_player((msg['source'].guild.id,voice_channel_id)).skip()
						except Exception as e:
							return msg['source'].reply('nihuya net igraet sha, infa sotka\na na dele:{}'.format(e))
					else:
						if (msg['source'].guild.id,voice_channel_id) in self.guilds:
							if track_nums < len(self.guilds[(msg['source'].guild.id,voice_channel_id)]):
								while track_nums > 0:
									self.get_player((msg['source'].guild.id,voice_channel_id)).skip()
									track_nums -= 1
								return msg['source'].reply('okkk....ia skiped!')
							else:
								return msg['source'].reply('ne mogu skipnut')
						else:
							return msg['source'].reply('nihuya net igraet sha, infa 100%!')
					return msg['source'].reply('lana')
				else:
					return msg['source'].reply('tak ya nichego ne igrau')	

			else:
				return msg['source'].reply(helper)
		except Exception as e:
			try:
				msg['source'].client.api.channels_messages_create(378492634404093953, content = u"in msg:\n {}\n\nerror:\n{}".format(msg['body'], traceback.format_exc()))
			except:
				print 'error send report'
				traceback.print_exc()
				pass
			return msg['source'].reply('nu ebana ya doljen bit v kanale zo zvukom.... ok da??\n\na na samom dele oshibka: {}'.format(e))		
			
		#self.dc.respond(msg,'hello food')
		