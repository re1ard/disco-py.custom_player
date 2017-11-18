# -*- coding: utf-8 -*-
import traceback
import urllib
import re
import gevent
import youtube_dl

from disco.bot import Plugin
from disco.bot.command import CommandError
from player import Player
from player_codecs import BufferedOpusEncoderPlayable, FFmpegInput
from disco.voice.client import VoiceException

from vk_api.audio import VkAudio
from vk_api import VkApi

from playlist_support import found_playlist,get_playlist,scrap_data_playlist

class DiscordPlugin:
	def __init__(self,dc):
		self.dc = dc
		self.desc = 'magnitola,m,магнитола,м <arg> - voisproizvedenie muziki v golosovoy chat\n'
		self.desc_priory = 'audio'
		api = VkApi('login','password')
		api.auth()
		self.vkaudio = VkAudio(api)
		self.guilds = {}
		self.search = {}
		print u'magnitola'
		self.ydl = youtube_dl.YoutubeDL()
		self.settings = {}

	def inactivitycheck(self):
		print 'this shit started!!'
		while True:
			gevent.sleep(1800)
			for guild_id in self.guilds.keys():
				player = self.get_player(guild_id)
				try:
					if not player.queue._event.ready():
						player.complete.set()
						player.client.disconnect()
				except:
					pass

	def getkeys(self):
		keys = [u'magnitola',u'магнитола',u'm',u'м',u'magnitofon',u'магнитофон']
		plugin_container = {}
		for key in keys:
			plugin_container[key] = self
		return plugin_container

	def get_player(self, guild_id):
		if guild_id not in self.guilds:
			raise CommandError("I'm not currently playing music here.")
		return self.guilds.get(guild_id)

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

з,j,join,войди,сюды - chtob zavalitsya v golosovoy chat
у,l,leave,съеби,уйди - chtoba ya s'ebal iz golosovogo

и,п,p,play,сыграй,взбрынцай <link> - proigrat govninu po ssile
retard m p http://youtube....
retard m play http://vk.com/audio.....playlist.....audio_playlist270279842_68104179
retard m p http://server.domain/mocha.mp3.....

н,q,search,найди <request> - naydet i vidas 20 resulatov
retard m q retardbot
retard m <track number> - to play

с,s,stop,стопе,хорош - skipnet tekuschiy track
pp,pause,погодь - stavit na pausu
resume,валяй,r - voisproizvodit track s pausi

setbass [-50...50] - dobavit bassssssssa!!	
						"""

		args = msg['body'].split()
		try:
			command = args[2]
		except:
			return msg['source'].reply(helper)

		if command in [u"setbass"]:
			try:
				count = int(args[3])
			except:
				return msg['source'].reply(u"nu ebana vvedi CHISLO... TOEST\nretard m setbass 30")
			if count > 50 or count < -50:
				return msg['source'].reply(u"ti che ebanutiy vvedi chislo ot -50 do 50")
			self.settings[msg['user_id']]['bass'] = count
			return msg['source'].reply('bass setted!')

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
				except IndexError:
					return msg['source'].reply(self.dc.markdown.blue(u'kruto trolish.....\n\n dlya 1 klassa\n\n vvedi nomer iz dostupnih debil'))

		if command in [u'leave',u'съеби',u'уйди',u'l',u'у']:
			if msg['source'].guild.id in self.guilds:
				player = self.get_player(msg['source'].guild.id)
				#index = self.guilds
				if player:
					player.disconnect()
					del self.guilds[msg['source'].guild.id]
					return msg['source'].reply('pokedova')
				else:
					return msg['source'].reply('nu okeeeeeey?')
			else:
				return msg['source'].reply('y menya v db napisano,chto menya zdes net')

		if command in [u'join',u'войди',u'сюды',u'j',u'з']:
			if msg['source'].guild.id in self.guilds:
				return msg['source'].reply('ya uje tut ueba...')
			
			state = msg['source'].guild.get_member(msg['source'].author).get_voice_state()
			if not state:
				return msg['source'].reply('nu epta ti sam v golosovoy chat voydi...')

			try:
				client = state.channel.connect()
			except VoiceException as e:
				return msg['source'].reply('ay blya ne mogu viyti v golosovoy anal, problema: `{}`'.format(e))

			msg['source'].reply('tak zahodim ebana........')
			self.guilds[msg['source'].guild.id] = Player(client)
			self.guilds[msg['source'].guild.id].complete.wait()
			msg['source'].reply("ya dau po s'ebam raz uj prosto tak siju i kayfuu zdesya..!")
			if msg['source'].guild.id in self.guilds:
				del self.guilds[msg['source'].guild.id]
			return
 
		try:
			if not msg['source'].guild.id in self.guilds:
				return msg['source'].reply('nujno chtob ya bil v kanale so zvukom')
				
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
					except:
						return msg['source'].reply('vk api error')
				if not response:
					return msg['source'].reply('nichego ne nashel')
				text = u'enter:\nretard magnitola <number>\n\nnum duration name:\n'
				for track in response:
					text += u'%02d: %03ds: %s - %s\n' % (response.index(track),int(track['dur']),track['artist'],track['title'])
					
				self.search[(msg['source'].guild.id,msg['source'].author.id)] = (response,page,q)
				return msg['source'].reply(text[:1999])
	
			if command in [u'play',u'сыграй',u'взбрынцай',u'p',u'и',u'п']:
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
							pre_cache = urllib.urlopen(url)
					except IOError:
						msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
						return self.call(msg)
					except UnicodeError:
						msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
						return self.call(msg)

				print url
				print found_playlist(url)
				if use_vk:
					#print use_vk
					item = FFmpegInput(use_vk,bass = bass_count).pipe(BufferedOpusEncoderPlayable)
				elif found_playlist(url):
					try:
						server_response = get_playlist(self.dc.vk,found_playlist(url)[0])
						tracks = scrap_data_playlist(server_response.text)
					except:
						return msg['source'].reply(self.dc.markdown.blue(u'vo vremya parsinga playlista proizoshla oshibka...'))
					text = 'playlist:\n'
					if not tracks:
						return msg['source'].reply(self.dc.markdown.blue(u'vozmojno danniy playlist yavlyatsya privatnim'))
					counter = 0
					for track in tracks:
						if counter > 19:
							break
						if track['dur'] < 1000:
							text += u'{}: {}s: {} - {}\n'.format(tracks.index(track),track['dur'],track['artist'],track['title'])
							self.get_player(msg['source'].guild.id).queue.append(FFmpegInput(track['url'],bass = bass_count).pipe(BufferedOpusEncoderPlayable))
						else:
							text += u'{}: {}s: {} - {} - SKIPPED\n'.format(tracks.index(track),track['dur'],track['artist'],track['title'])
					return msg['source'].reply(self.dc.markdown.block(text[:1999]))
				elif u'.mp3' in url and u'#FILENAME/' in url:
					msg['body'] = u'retard m p {}'.format(url.split(u'#FILENAME/')[0])
					return self.call(msg)
					#return msg['source'].reply(self.dc.markdown.blue(u'nu ti blya iz konca ssilki uberi #FILENAME/....\n\nponastavite govno pluginov na brauzer i ebetes v jeppu'))
				elif u'.mp3' in url and pre_cache.info().getheaders("Content-Length"):
					if int(pre_cache.info().getheaders("Content-Length")[0]) > 20971520:
						return msg['source'].reply(self.dc.markdown.blue(u'chta tvoya mp3 kakayata bolshaya kak tvoya mamka'))
					elif int(pre_cache.info().getheaders("Content-Length")[0]) > 8192:
						item = FFmpegInput(url,bass = bass_count).pipe(BufferedOpusEncoderPlayable)
					else:
						return msg['source'].reply(self.dc.markdown.blue(u'chta tvoya mp3 kakayata malenkaya'))
				elif pre_cache.info().type == 'audio/mpeg':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#item = FFmpegInput(url).pipe(BufferedOpusEncoderPlayable)
				elif pre_cache.info().type == 'audio/x-scpls':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#link = re.findall(r'http+.+\b',pre_cache.read())
					#if link:
					#	item = YoutubeDLInput(link[0]).pipe(BufferedOpusEncoderPlayable)
					#else:
					#	return msg['source'].reply(self.dc.markdown.blue(u'ya opredeliil, chto eto potok audio/x-scpls, tolko ssilku ne smog zaparsit'))
				elif pre_cache.info().type == 'video/x-ms-asf':
					return msg['source'].reply(self.dc.markdown.blue(u'not support direct raw'))
					#link = re.findall(r'http+.+\b',pre_cache.read())
					#if link:
					#	item = YoutubeDLInput(link[0]).pipe(BufferedOpusEncoderPlayable)
					#else:
					#	return msg['source'].reply(self.dc.markdown.blue(u'ya opredeliil, chto eto potok video/x-ms-asf, tolko ssilku ne smog zaparsit'))
				elif pre_cache.info().type == 'application/x-mpegurl':
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

					ytd = self.ydl.extract_info(url, download=False, process=False)

					if ytd['duration'] > 36000:
						msg['body'] = u'retard m p https://cs9-4v4.userapi.com/p23/3f07fb71ac5462.mp3?extra=wMx_0nOA4JmX8UyMK3CHgt97_I4K27KOnFiGhTgWLOlkWAwJMbv1d6DWV2Ak6i2hHNOU9_iHgYc4NAlXVFFXjAzQCIFGWv5kwmcu_iVWDGGIvRm9F0kcWNIZslyrNC7l-kkXTF3LNwx-cA'
						msg['source'].reply('chto lubitel prodoljovatih predmetov???')
						return self.call(msg)
					if ytd['duration'] > 3500:
						msg['source'].reply('vot skaji vo chesnaku nahuya mne igrat celiy chas??')
						msg['body'] = u'retard m p https://psv4.userapi.com/c813120/u354292611/audios/d29ea78293a5.mp3?extra=KbVS4CFu5f6QHR6468VHAe226clX1p9MRBXHSKzo-zN_CRKpUHaRQ8YRkNAT34tHXjE0Mx47VoODDBxDvdImnYCzI2tICcqkFzp_jp_qcfjhw3W847duieE7ZTJHkhch2aK3BNMROen4dA'
						return self.call(msg)
					if ytd['duration'] > 1800:
						return msg['source'].reply(self.dc.markdown.blue(u'ebaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaat ona dlinnaya kak moy houy...'))
					url = ytd['formats'][0]['url']
					item = FFmpegInput(url,bass = bass_count).pipe(BufferedOpusEncoderPlayable)
				else:
					ytd = self.ydl.extract_info(url, download=False, process=False)
					if not 'duration' in ytd:
						return msg['source'].reply("i kak ya uznau...., chto eto huynya ne ub'et menya.. ya hz skoka ona dlitsya")
					if ytd['duration'] > 1800:
						return msg['source'].reply(self.dc.markdown.blue(u'ebaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaat ona dlinnaya kak moy houy...'))
					url = ytd['formats'][0]['url']
					item = FFmpegInput(url,bass = bass_count).pipe(BufferedOpusEncoderPlayable)
				self.get_player(msg['source'].guild.id).queue.append(item)
				return msg['source'].reply('nu chtoj rvi dushu sanya...\n tvoe mesto v ocheredi, vrode kak: %s' % len(self.guilds[msg['source'].guild.id].queue))
	
			if command in [u'pause',u'погодь',u'pp']:
				if msg['source'].guild.id in self.guilds:
					try:
						self.get_player(msg['source'].guild.id).pause()
					except AttributeError:
						return msg['source'].reply('nihuya net igraet sha, infa sotka')
					return msg['source'].reply('jdem, poka ti razrodishsya')
				else:
					return msg['source'].reply('tak ya nichego ne igrau')
	
			if command in [u'resume',u'валяй',u'r']:
				if msg['source'].guild.id in self.guilds:
					try:
						self.get_player(msg['source'].guild.id).resume()
					except AttributeError:
						return msg['source'].reply('nihuya net igraet sha, infa sotka')
					return msg['source'].reply('rvem dushu')
				else:
					return msg['source'].reply('tak ya nichego ne igrau')

			if command in [u'stop',u'стоп',u'стопе',u'хорош',u's',u'с']:
				if msg['source'].guild.id in self.guilds:
					try:
						track_nums = int(args[3])
					except:
						track_nums = None

					if True:
						try:
							current_player = self.get_player(msg['source'].guild.id)
							current_player.skip()
						except Exception as e:
							return msg['source'].reply('nihuya net igraet sha, infa sotka\na na dele:{}'.format(e))
					else:
						if msg['source'].guild.id in self.guilds:
							if track_nums < len(self.guilds[msg['source'].guild.id]):
								while track_nums > 0:
									self.get_player(msg['source'].guild.id).skip()
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
		