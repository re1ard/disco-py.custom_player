# -*- coding: utf-8 -*-
import traceback
import requests
import re
import gevent
import youtube_dl
import six

from json import loads
import subprocess

from datetime import timedelta as sectohum
from time import time
from random import choice, randint, shuffle

from disco.bot import Plugin
from disco.bot.command import CommandError
from player import Player
from player_codecs import BufferedOpusEncoderPlayable, FFmpegInput
from disco.voice.client import VoiceException
from disco.voice.client import VoiceClient
from disco.voice.client import VoiceState
from disco.types.message import MessageEmbed

from vk_api.audio import VkAudio
from vk_api import VkApi

from playlist_support import found_playlist,get_playlist,scrap_data_playlist,found_user_audio_page
import magnitola_errors

class PlayerQueue:
	queue = []

	def __bool__(self):
		return True if len(queue) else False

	def clear(self):
		self.queue = []
		return True

	#def append(self,**kwargs):

	def delete(self,uid):
		total = len(self.queue)
		while total:
			if self.queue[total-1].uid == uid:
				del self.queue[total-1]
			total -= 1
		return True

class VoiceServer:
	player = None
	connecting = False
	queue = PlayerQueue()

	def __init__(self,client,**kwargs):
		self.client = client
		for key,data in kwargs.items():
			setattr(self,key,data)
			#gid,tcid,vcid,uid
	
	def player_setup(self):
		max_reconnects = 5
		sleep_time = 5
		while not self.player and max_reconnects:
			try:
				self.connecting = True
				self.player = Player(VoiceClient(self.client.state.guilds.get(self.gid).get_voice_state(self.uid)))
				self.player.connect()
			except Exception as error:
				max_reconnects -= 1
				problem = error
				self.player = None
				print u"Connecting Problem: {} in {} guild, sleep {} sec.....".format(self.gid,error,sleep_time)
				gevent.sleep(sleep_time)
		
		self.connecting = False
		if not self.player:
			raise magnitola_errors.ConnectingProblems(u"Have error: {} after 5 reconnects, try again later...".format(problem))

		self.vcid = self.player.client.channel.id
		return True

	def set_vcid(self,vcid):
		self.vcid = vcid
		return True

	def get_state(self):
		return self.player.client.state if player else VoiceState.DISCONNECTED

	def set_wait(self):
		self.player.complete.wait()
		return True

	def connect(self):
		if self.player and self.player.client.state == VoiceState.CONNECTED:
			raise magnitola_errors.VoiceConnected(u"Voice client already connected to VoiceServer")
		if self.connecting:
			raise magnitola_errors.ConnectingWait(u"Please just wait, blyat suka ti tupaya")
		self.player_setup()
		return True

	def disconnect(self,**kwargs):
		if (self.queue or self.player.now_playing) and not kwargs.get(u"force",True):
			if kwargs.get(u"uid",None):
				self.queue.delete(kwargs.get(u"uid",None))
				if self.queue:
					raise magnitola_errors.QueueNotEmpty(u"Your queue clear")
			else:
				raise magnitola_errors.QueueNotEmpty(u"Queue is not empty")
		
		if self.player:
			try:
				self.queue.clear()
				self.player.force_kick = True
				self.player.skip() if self.player.now_playing else None
			except Exception as error:
				print error
				pass
			try:
				self.player.disconnect()
			except Exception as error:
				print error
				pass
		
		return True


class VoiceServers:
	servers = {}
	__getitem__ = servers.__getitem__

	def __init__(self,plugin):
		self.plugin = plugin

	def working(self,guild_id):
		return True if int(guild_id) in servers.values() else False

	def append(self,**kwargs):
		if self.working(guild_id):
			raise magnitola_errors.AlreadyWorking(u"Voice in servers")
		self.servers[int(guild_id)] = VoiceServer(self.plugin.dc.DISCORD_CORE.bot.client, **kwargs)
		return True

	def delete(self,gid,**kwargs):
		self.servers[int(gid)].disconnect(**kwargs)
		del self.servers[int(gid)]
		return True

class FakeChannel:
	id = 0

class FakeHeader:
	headers = {'Content-Type':'None'}

class FakeHeaderStream:
	headers = {'Content-Type':'AudioStream'}

class EmbedPlaylist:
	field_max_ch = 1024 - 256
	embed_max_ch = 6000 - 500
	page_number = 1
	def __init__(self,number,track_number = - 1):
		self.embed = MessageEmbed()
		self.field = u""
		self.embed.set_author(name=u"Result #{}".format(number))
		self.embed.set_footer(text='Powered RetardBot Engine | https://discord.gg/tG35Y4b | gsd#6615')
		self.total_symb = 50
		self.track_number = track_number

	def append(self,artist,title,duration):
		self.track_number += 1
		text = u"{}|{}|{} - {}\n".format(self.track_number,sectohum(seconds=int(duration)),artist,title)
		self.field += text
		self.total_symb += len(text)
		#######################################
		if len(self.field) > self.field_max_ch:
			self.embed.add_field(name=u"Page: {}".format(self.page_number), value=unicode(self.field), inline=True)
			self.field = ""
			self.page_number += 1

		if self.total_symb > self.embed_max_ch:
			return True
		else:
			return False

class UserSetting:
	value = 0
	adbulov = False

class DiscordPlugin:
	max_one_part_lenght = 1500
	connecting_guild = {}
	wait_react_cmd = {}#guild:[] '🇵','🇸','🇱','🇶','🇾' '🇯' u'0⃣',u'1⃣',u'2⃣',u'3⃣',u'4⃣',u'5⃣',u'6⃣',u'7⃣',u'8⃣',u'9⃣'
	react_to_cmd = {u'🇵':('p',True,u'need link, send this(ссылку скинь ебанат)'),u'🇸':('s',False,''),u'🇯':('j',False,''),u'🇱':('l',False,''),u'🇶':('q',True,u'enter request(введи то что ты ищушь во вк)'),u'🇾':('yts',True,u'enter'),u'0⃣':('0',False,''),u'1⃣':('1',False,''),u'2⃣':('2',False,''),u'3⃣':('3',False,''),u'4⃣':('4',False,''),u'5⃣':('5',False,''),u'6⃣':('6',False,''),u'7⃣':('7',False,''),u'8⃣':('8',False,''),u'9⃣':('9',False,''),}
	users_wait_requests = {}#guild:{'user_id':msg}
	def __init__(self,dc):
		self.dc = dc
		self.desc = 'magnitola,m,магнитола,м <arg> - voisproizvedenie muziki v golosovoy chat\n'
		self.desc_priory = 'audio'
		self.vkaudio = VkAudio(dc.vk)
		self.guilds = {}
		self.iq_test = {}
		self.search = {}
		print u'magnitola'
		self.ydl = youtube_dl.YoutubeDL({'usenetrc':True,'quiet':True,"noplaylist":True})
		self.ydl_pl = youtube_dl.YoutubeDL({'usenetrc':True,'quiet':True,"noplaylist":False})
		self.settings = {}
		self.parse_cmd = u"ffprobe -print_format json -loglevel panic -show_entries stream=codec_name:format -select_streams a:0 -i {}"
		self.wait_connect = {}
		self.wait_playlist = {}
		self.region_wait = {}
		self.last_time_inactivity_check = time()
		self.last_time_alone_check = time()
		################################################################
		self.search_cmds = [u'search',u'найди',u'q',u'н']
		self.join_cmds = [u'join',u'зайди',u'сюды',u'j',u'з',u'сюда']
		self.help_cmds = [u'help',u'хелп',u'помощь']
		self.leave_cmds = [u'leave',u'съеби',u'уйди',u'l',u'у']
		self.play_cmds = [u'play',u'проиграй',u'взбрынцай',u'p',u'и',u'п']
		self.playplaylist_cmds = [u"ppl",u"pplaylist"]
		self.stop_cmds = [u'stop',u'стоп',u'стопе',u'хорош',u's',u'с',u'c']
		self.ytd_search_cmds = [u'ytsearch',u'yts',u'ytq']
		self.now_cmds = [u'now',u'сейчас',u'n',u'се',u'сe']
		self.pause_cmds = [u'pause',u'погодь']
		self.playlist_cmds = [u'playlist',u'плейлист',u'пл',u'pl']
		self.resume_cmds = [u'resume',u'валяй',u'r']
		self.setbass_cmds = [u"setbass",u"sb",u"bass",u"басс"]
		self.shuffle_cmds = [u"shuffle",u"random",u"перемешать"]
		self.change_text_channel_cmds = [u"tch"]
		self.replay_cmds = [u"replay"]
		################################################################

	def inactivitycheck(self):
		print u"Inactivity Check"
		max_delay_in_voice = 600
		while True:
			gevent.sleep(60)
			self.last_time_inactivity_check = time()
			temporary = list(self.guilds.keys())
			for guild_id in temporary:
				try:
					if time() - self.get_player(guild_id)['player'].last_activity > max_delay_in_voice:
						try:
							self.get_player(guild_id)['player'].complete.set()
						except Exception as error:
							print u"gid: {} error: {}".format(guild_id,error)
						print u"gid: {} leave: {}".format(guild_id,self.leave(guild_id))

					elif not self.get_player(guild_id)['player'].client.channel.guild:
						print 'kicked from gid(kicked me from this): {}'.format(guild_id)
						print self.leave(gid)
				except Exception as e:
					print "Force kick in gid: {}, have error: {}".format(guild_id,e)
					pass

	def alone_check(self,guild_id):
		its_me = False
		try:	
			if self.get_player(guild_id)['player'].client.channel.guild and len(self.get_player(guild_id)['player'].client.channel.guild.voice_states.keys()) <= 1:
				if len(self.get_player(guild_id)['player'].client.channel.guild.voice_states.keys()) == 1:
					try:
						if self.get_player(guild_id)['player'].client.channel.guild.get_voice_state(self.get_player(guild_id)['player'].client.channel.guild.client.state.me):
							its_me = True
					except Exception as e:
						its_me = True
						print e		
				else:
					its_me = True

			if its_me:
				print u"gid: {} leave: {}".format(guild_id,self.leave(guild_id))
		except Exception as e:
			print "Force kick in gid: {}, have error: {}".format(guild_id,e)
			pass

		return True

	def alonecheck(self):
		print u"Alone Check"
		while True:
			gevent.sleep(180)
			self.last_time_alone_check = time()
			temporary = list(self.guilds.keys())
			for gid in temporary:
				try:
					gevent.spawn(self.alone_check,guild_id = gid)
				except Exception as error:
					print u"gid: {}, error: {}".format(gid,error)

	def getmetadata(self,url):
		output = {'stream':False,'streams':False}
		try:
			response = loads(subprocess.check_output(self.parse_cmd.format(url).split()))
			output.update({'size':int(response['format'].get('size',0))})
			output.update({'duration':int(float(response['format'].get('duration',0)))})
			output.update({'artist':response['format'].get(u'tags',{}).get(u'artist',response['format'].get(u'tags',{}).get(u'icy-name','Unknown Artist'))})
			output.update({'title':response['format'].get(u'tags',{}).get(u'title',response['format'].get(u'tags',{}).get(u'StreamTitle','Unknown Title'))})
			if not output['duration']:
				output['stream'] = True
			if response['streams']:
				output['streams'] = True
				
			return output
		except subprocess.CalledProcessError:
			return output

	def getkeys(self):
		self.fast_calls = [u'sb',u'j',u'з',u'l',u'у',u'q',u'н',u'p',u'и',u'п',u'n',u'pl',u'се',u'сe',u'pp',u'r',u's',u'с',u'c']
		self.plugin_keys = [u'magnitola',u'магнитола',u'm',u'м',u'magnitofon',u'магнитофон'] + self.fast_calls
		#without_ex = [u"setbass",u"sb",u'join',u'зайди',u'сюды',u'j',u'з',u'сюда',u'leave',u'съеби',u'уйди',u'l',u'у',u'search',u'найди',u'q',u'н',u'ytsearch',u'yts',u'ytq',u'play',u'проиграй',u'взбрынцай',u'p',u'и',u'п',u'now',u'сейчас',u'n',u'се',u'сe',u'playlist',u'плейлист',u'пл',u'pl',u'pause',u'погодь',u'pp',u'resume',u'валяй',u'r',u'stop',u'стоп',u'стопе',u'хорош',u's',u'с',u'c']
		plugin_container = {}
		for key in self.plugin_keys:
			plugin_container[key] = self
		return plugin_container

	def get_player(self, guild_id):
		if guild_id not in self.guilds:
			return {}
		return self.guilds.get(guild_id)

	#def cool_response(self,respond_method, content, reactions = [], wait = ''):
		
	def cool_response(self,msg,response = u"",preset = 'help',cut = 0,embed_attch = None):
		if msg.get('button',False):
			return 0
		if not msg['source'].guild.id in self.wait_react_cmd:
			self.wait_react_cmd[msg['source'].guild.id] = []
		elif len(self.wait_react_cmd.get(msg['source'].guild.id,[])) > 30:
			self.wait_react_cmd[msg['source'].guild.id] = self.wait_react_cmd.get(msg['source'].guild.id,[])[-30:]
		################################################################
		msg_create = msg['source'].reply(response,embed = embed_attch)
		################################################################
		try:
			if preset == 'help':
				self.add_more_reaction(msg_create,['🇵' if msg['source'].guild.id in self.guilds else None,'🇸' if msg['source'].guild.id in self.guilds and self.get_player(msg['source'].guild.id)['player'].already_play else None,'🇶' if msg['source'].guild.id in self.guilds else None,'🇾' if msg['source'].guild.id in self.guilds else None, '🇯' if not msg['source'].guild.id in self.guilds else '🇱'])
			elif preset == 'numbers':
				self.add_more_reaction(msg_create,[u'0⃣',u'1⃣',u'2⃣',u'3⃣',u'4⃣',u'5⃣',u'6⃣',u'7⃣',u'8⃣',u'9⃣'][:cut])
			#elif preset == 'play':
			#	return msg_create
			#	#self.add_more_reaction(msg_create,['🇵' if msg['source'].guild.id in self.guilds else None,'🇸' if msg['source'].guild.id in self.guilds and self.get_player(msg['source'].guild.id)['player'].already_play else None,'🇱' if msg['source'].guild.id in self.guilds else None,'🇶' if msg['source'].guild.id in self.guilds else None,'🇾' if msg['source'].guild.id in self.guilds else None])
			elif preset == 'join':
				self.add_more_reaction(msg_create,['🇯' if not msg['source'].guild.id in self.guilds else '🇱'])
		except:
			pass
		else:
			self.wait_react_cmd[msg['source'].guild.id].append(msg_create.id)
		return msg_create

	#def input_cmd(self,event):
		
	def add_more_reaction(self,msg,react_list=[]):
		for reaction in react_list:
			if reaction:
				msg.add_reaction(reaction)
		return

	def leave(self,guild_id,force = True,user_id = None):
		if guild_id in self.guilds:
			player = self.get_player(guild_id)['player']
			if (player.queue._data or getattr(player.now_playing,'source',0)) and not force:
				if user_id:
					item_num_to_delete = []
					shift = 1
					for item in player.queue._data:
						if item.source.user_id == user_id:
							item_num_to_delete.append(player.queue._data.index(item))
					for num_item in item_num_to_delete:
						shift -= 1
						del player.queue._data[num_item+shift]

					if len(player.queue._data):
						return u'tvoya ochered udalena k huyam, no pomimo tebya tam cheto govno esche est(('
				else:
					return u'ne ne uydu poka igrau muziku..'
			e = None
			if player:
				player.force_kick = True
				player.queue._data = []
				try:
					if getattr(player.now_playing,'source',0):
						player.skip()
				except Exception as e:
					print e
					pass
				##################################################
				try:
					player.disconnect()
				except Exception as e:
					print e
					pass
				if guild_id in self.guilds:
					del self.guilds[guild_id]
				del player
				if e:
					return u'pokedova\n\nwe have error:{}'.format(e)
				else:
					return u'pokedova'
			else:
				return u"nu okeeeeeey?"
		else:
			return u"y menya v db napisano,chto menya zdes net"


	def call(self,msg):
		#if not msg['user_id'] in self.dc.DISCORD_CORE.retard.RETARD_DEBUG_USERS_ID:
		#	return msg['source'].reply(u"senya bez muziki ibo magnitola skazala allah!!")


		if msg['user_id'] in self.settings:
			bass_count = UserSetting()#self.settings[msg['user_id']]['bass']
			bass_count.value = self.settings[msg['user_id']]['bass']
			abdulov = self.settings[msg['user_id']]['abdulov']
			replay = self.settings[msg['user_id']]['replay']
		else:
			self.settings.update({msg['user_id']:{'bass':0,'abdulov':False,'replay':False}})
			abdulov = False
			replay = False
			bass_count = UserSetting()
		if not msg['source'].guild:
			return msg['source'].reply(u"ti blya poymi, ovosch... chto v ls ya muzin igrat ne mogu, potomu chto ya bot, a ne chelovek... poetomu soezvol nayti server.... ah da y tebya je net druzey")
		q = None
		direct_url = None
		offset = 0
		live_stream_url = False
		puten = True if randint(0,71) == 46 else False
		helper = """
nu ebat vvedi comandu:
retard magnitola <cmd> <arg>

[j]oin,[з]айди,сюды - chtob zavalitsya v golosovoy chat
[l]eave,[у]йди,съеби - chtoba ya s'ebal iz golosovogo
ili je uberet tvou ochered' k huyam, esli ona imeet'sya
CHTOB NE DROCHIT' BUKVU S SUDA SMONTRI EPTA

[p]lay,[п]ро[и]грай,взбрынцай <link> - proigrat govninu po ssikle
retard m p http://youtube....
retard m play http://vk.com/audios27919760......audio_playlist270279842_68104179
retard и http://server.domain/mocha.mp3.....
retard м и http://pdxrr.com:8090
retard p http://italo.live-streams.nl/live.m3u

[ppl]aylist <link> - sigrat' playlist s youtube i etc(NE S VK.COM)
retard m ppl https://www.youtube.com/playlist?list=PLWCzwRujF35WdCJS7lIxp5IArkESChpkP

[н]айди,search,q <request> - naydet i vidas resultati s vk
[yts]earch,ytq <request> - naydet i vidas resultati s youtube
retard m q retardbot
retard m <track number> - to play

[s]top,[с]топ,хорош - skipnet tekuschiy track
pp,pause,погодь - stavit na pausu
[r]esume,валяй - voisproizvodit track s pausi
[n]ow,[се]йчас - chto sha igraet
[pl]aylist,[пл]ейлист - pokajet ochered
shuffle,random,перемешать - peremeshat playlist

tch <channel> - izmenit kanal dlya textovih soobscheniy
replay - postavit' na replay player ili net
setbass,sb,bass,басс [-50...50] - dobavit bassssssssa!!
replay - postavit' next track na replay
abdulov - izmenit na goloz abdulya(test cmd)

komandi imeuschei dlinu men'she 3 znakov(v kvadratnih skobkah) mojno vvodit' bez m/magnitola

tips: {}	
"""
		helper = helper.format(choice([u"tvoe mnenie ne uchitivaet'sya esli y tebya anime na ave",u"esli retard ne igraet s och..... v kanale, a ti vvel komandu chtob igral, sdelay tak chtobi on perezashel v kanal"]))
		args = msg['body'].split()

		if args[1].lower() in self.fast_calls:
			msg['body'] = u"retard magnitola" + msg['body'][len(args[0]):]
			#print msg['body']
			return self.call(msg)

		try:
			command = args[2].lower()
		except:
			return self.cool_response(msg,helper)

		if command in self.setbass_cmds:
			try:
				count = int(args[3])
			except:
				return msg['source'].reply(u"nu ebana vvedi CHISLO... TOEST\nretard m setbass 30")
			if count > 50 or count < -50:
				return msg['source'].reply(u"ti che ebanutiy vvedi chislo ot -50 do 50")
			self.settings[msg['user_id']]['bass'] = count
			return msg['source'].reply(u'bass setted!\n result listen in next use play command')

		if command in [u"abdulov"]:
			if abdulov:
				self.settings[msg['user_id']]['abdulov'] = False
			else:
				self.settings[msg['user_id']]['abdulov'] = True
			return msg['source'].reply(u"abdulov setted!\n result listen in next use play command\n use abdul':{}".format(self.settings[msg['user_id']]['abdulov']))

		if command in [u"replay"]:
			if abdulov:
				self.settings[msg['user_id']]['replay'] = False
			else:
				self.settings[msg['user_id']]['replay'] = True
			return msg['source'].reply(u"replay setted!\n result listen in next use play command\n use replay':{}".format(self.settings[msg['user_id']]['replay']))

		if (msg['source'].guild.id,msg['user_id']) in self.search and ((len(args) > 2 and args[1] in self.plugin_keys and args[2].isdigit() and len(args) == 3) or (len(args) > 3 and args[1] in self.plugin_keys and args[2] in self.plugin_keys and args[3].isdigit() and len(args) == 4)):# and ((len(args) > 3 and args[3].isdigit() and args[2] in self.search_cmds and len(args) == 4) or (len(args) > 2 and args[2].isdigit() and len(args) == 3)):
			try:
				track_number = int(args[2])
			except:
				try:
					track_number = int(args[3])
				except:
					del self.search[(msg['source'].guild.id,msg['user_id'])]
					return self.call(msg)
			command = u"play"
			if False:# track_number > 49:
				offset = self.search[(msg['source'].guild.id,msg['user_id'])][1] * 20
				page = self.search[(msg['source'].guild.id,msg['user_id'])][1] + 1
				command = 'q'
				q = self.search[(msg['source'].guild.id,msg['user_id'])][2]
			else:
				try:
					direct_url = self.search[(msg['source'].guild.id,msg['user_id'])][0][track_number]['url']
					title = self.search[(msg['source'].guild.id,msg['user_id'])][0][track_number]['title']
					artist = self.search[(msg['source'].guild.id,msg['user_id'])][0][track_number]['artist']
					duration = self.search[(msg['source'].guild.id,msg['user_id'])][0][track_number]['duration']
				except IndexError:
					return msg['source'].reply(self.dc.markdown.blue(u'kruto trolish.....\n\n dlya 1 klassa\n\n vvedi nomer iz dostupnih debil'))

		try:
			voice_channel_id = msg['source'].guild.get_voice_state(msg['source'].author).channel_id
		except AttributeError:
			return msg['source'].reply(u'nu epta ti sam v golosovoy chat voydi...')

		try:
			my_voice_channel_id = msg['source'].guild.get_voice_state(msg['source'].client.state.me).channel_id
		except Exception as e:
			my_voice_channel_id = 0

		if command in self.help_cmds:
			return self.cool_response(msg,helper)

		if command in self.shuffle_cmds:
			if self.get_player(msg['source'].guild.id)['player'].queue._data:
				self.get_player(msg['source'].guild.id)['player'].queue.shuffle()
				return msg['source'].reply(u'peremeshano kak govno v shtanah')
			else:
				return msg['source'].reply(u'tam net trekov,tak chto i peremeshivat nechego...')
			
		if command in ['fakejoin'] and msg['user_id'] in self.dc.DISCORD_CORE.retard.RETARD_DEBUG_USERS_ID:
			if msg['source'].guild.id in self.guilds and self.guilds[msg['source'].guild.id]['player']:
				return msg['source'].reply(u'ya uje tut')
			elif msg['source'].guild.id in self.guilds and not self.guilds[msg['source'].guild.id]['player']:
				del self.guilds[msg['source'].guild.id]
			self.guilds[msg['source'].guild.id] = {'voice_id':0,'player':None,'reply':msg['source'].reply,'wait':{},'disconnected':False}
			#self.guilds[msg['source'].guild.id]['player'].text_id = msg['source'].channel.id
			return msg['source'].reply(u'created')

		if command in self.join_cmds:
			if msg['source'].guild.id in self.guilds:
				if my_voice_channel_id == voice_channel_id:
					return msg['source'].reply(u'ya uje tut ueba...')
				else:
					try:
						if self.get_player(msg['source'].guild.id)['player'].now_playing and self.get_player(msg['source'].guild.id)['player'].now_playing.source:
							if self.get_player(msg['source'].guild.id)['player'].client.state == VoiceState.DISCONNECTED:
								print self.leave(msg['source'].guild.id)
								return self.call(msg)
							return msg['source'].reply(u'ya seychas tusuus v drugom kanale... tak chto poprosi teh rebyat osvobodit menya ili perenesti suda...')
						else:
							return msg['source'].reply(u"vrode kak... ya uje tut i prosto siju nihuya ne delau... ved' tak?")
					except TypeError:
						print self.leave(msg['source'].guild.id)
						return self.call(msg)

					except AttributeError:
						print self.leave(msg['source'].guild.id)
						return self.call(msg)

					except Exception as e:
						msg['source'].reply(u'spasibo(thanks) ebat chto nashel oshibku kotoruy ya esche ne obrabotal да блять спасибо БОЛЬШОЕ!!')
						return self.dc.DISCORD_CORE.error_report(text=msg['body'], error=e, traceinfo=traceback.format_exc())

			if msg['source'].guild.id in self.guilds and not self.guilds[gid]['voice_id'] == voice_channel_id:
				return msg['source'].reply(u'ya uje est na dannom servere, gdeto v golosovom chate...')
			
			state = msg['source'].guild.get_member(msg['source'].author).get_voice_state()
			if not state:
				return msg['source'].reply(u'nu epta ti sam v golosovoy chat voydi...')

			if msg['user_id'] in self.iq_test:
				del self.iq_test[msg['user_id']]

			if msg['source'].guild.id in self.connecting_guild:
				return msg['source'].reply(u'padaji ebana poka ya zaydu.... esche chutok..')

			if msg["source"].guild.region in self.region_wait:
				sec = 0.0
				for t_sec in self.region_wait[msg["source"].guild.region]:
					sec += t_sec
				try:
					region_wait = u"srednee vremya ojidaniya v regione ({}): {:.5} sec".format(msg["source"].guild.region,sec/len(self.region_wait[msg["source"].guild.region]))
				except:
					region_wait = u''
			else:
				region_wait = u""
				self.region_wait[msg["source"].guild.region] = []

			msg['source'].reply(u'tak ebana.... jdems poka ya zaydu...\n'+region_wait)
			
			start_connect = time()
			self.connecting_guild[msg['source'].guild.id] = True
			try:
				print 'connect to state'
				#client = state.channel.connect()
				client = VoiceClient(state.channel, max_reconnects = 1)
				client.connect()
			except VoiceException as e:
				print "Try connect to state, error: {}".format(e)
				player = self.guilds.get(msg['source'].guild.id,{}).get('player',0)
				if player and not msg.get('voice_solution',0):
					print "Force join to channel"
					try:
						player.force_kick = True
					except:
						print 'failed force kick'
						pass
					try:
						player.queue._data = []
					except:
						print 'failed clean queue'
						pass
					try:
						player.disconnect()
					except:
						print 'failed disconnect'
						pass
					if msg['source'].guild.id in self.guilds:
						del self.guilds[msg['source'].guild.id]
					msg['voice_solution'] = True
					del player
					return self.call(msg)
				else:
					try:
						print 'force create voiceclient'
						client = VoiceClient(state.channel, max_reconnects = 1)
						client.connect()
					except Exception as e:
						print 'error: {}'.format(e)
						return msg['source'].reply(u'ay blya ne mogu voyti v golosovoy anal(2), problema: `{}`'.format(e))
					try:
						print 'force disconnect'
						client.disconnect()
					except Exception as e:
						print 'eeror: {}'.format(e)
						pass
					try:
						print 'try connect'
						client.connect()
					except Exception as e:
						try:
							client.disconnect()
						except:
							pass
						print 'error: {}'.format(e)
						return msg['source'].reply(u'ay blya ne mogu voyti v golosovoy anal(3), problema: `{}`\n\npoprobuy esche razok sdelat tak chtob ya podkluchilsya'.format(e))	
			finally:
				if msg['source'].guild.id in self.connecting_guild:
					del self.connecting_guild[msg['source'].guild.id]					

			self.guilds[msg['source'].guild.id] = {'voice_id':voice_channel_id,'player':Player(client),'reply':msg['source'].reply,'wait':{},'disconnected':False}
			self.guilds[msg['source'].guild.id]['player'].text_id = msg['source'].channel.id
			
			if len(self.wait_react_cmd.get(msg['source'].guild.id,[])) > 30:
				self.wait_react_cmd[msg['source'].guild.id] = self.wait_react_cmd.get(msg['source'].guild.id,[])[1:]
			if not msg['source'].guild.id in self.wait_react_cmd:
				self.wait_react_cmd[msg['source'].guild.id] = []
			################################################################
			self.region_wait[msg["source"].guild.region].append(time()-start_connect)
			msg_create = msg['source'].reply(u'tak zahodim ebana........\ntime to connect: {} s'.format(time()-start_connect))
			################################################################
			self.wait_react_cmd[msg['source'].guild.id].append(msg_create.id)
			self.add_more_reaction(msg_create,['🇵','🇸','🇱','🇶','🇾'])
			#
			#
			if msg['source'].guild.id in self.guilds:
				self.guilds[msg['source'].guild.id]['player'].complete.wait()
			else:
				msg['source'].reply(u"chota poshlo ne tak.... tupa povtori commandu")
			#
			
			#
			if msg['source'].guild.id in self.guilds:
				self.guilds[msg['source'].guild.id]['disconnected'] = True
			if msg['source'].guild.id in self.guilds and not self.guilds[msg['source'].guild.id]['player'].force_kick:
				msg['source'].reply(u"ya dau po s'ebam raz uj prosto tak siju i kayfuu zdesya..!")
			if msg['source'].guild.id in self.guilds:
				del self.guilds[msg['source'].guild.id]
			return

		try:
			if not msg['source'].guild.id in self.guilds:
				####################################				
				#print '1'
				#if msg['source'].guild.id in self.connecting_guild:
				#	return msg['source'].reply(u"padaji poka ya zaydu")
				#
				#h_body = msg['body']
				#msg['body'] = u'retard m j'
				#print '2'
				#gevent.spawn(self.call,msg = msg)
				#print '3'
				#msg['body'] = h_body
				#
				#while not msg['source'].guild.id in self.guilds:
				#	print '4'
				#	gevent.sleep(2)
				#
				#print 'kek'
				#return self.call(msg)
				#####################################
				if msg['user_id'] in self.iq_test:
					return self.cool_response(msg,u'ti blyat poymi,chto ti nu ochen tupoy... ya tebe govoril NUJNO CHTOB TI, DADA TI IMENNO DOLBAEB, BIL V KANALE SO SVUKOM... KROME ETOGO YA NE DOLJEN BIT UJE NA KANALE NA ETOM SERVERE, I TI PITAESHYA ZASUNUT MENYA NA DRUGOY....\nTAKIH DEBILOV KAK TI NUJNI USIPLYAT,IBO VI BLYAT PROSTO EBANIY MUSOR\n\n PROSTO VVEDI: RETARD M J','join')
				else:
					self.iq_test[msg['user_id']] = True
					return self.cool_response(msg,u'nujno chtob ya bil v kanale so zvukom i chtob ti tam sam bil','join')
				#####################################
			else:
				if not voice_channel_id:
					return msg['source'].reply(u'nu ebana ti moget sam zaydesh v kanal so zvukom')

			if command in self.leave_cmds:
				if self.get_player(msg['source'].guild.id)['player'].client.channel.guild.voice_states.keys() <= 1:
					returned_msg = self.leave(msg['source'].guild.id,True)
				elif self.get_player(msg['source'].guild.id)['player'].client.channel.guild.voice_states.keys() == 2:
					if my_voice_channel_id:
						returned_msg = self.leave(msg['source'].guild.id,True)
					else:
						returned_msg = self.leave(msg['source'].guild.id,False,msg['user_id'])
				else:
					returned_msg = self.leave(msg['source'].guild.id,False,msg['user_id'])
				return msg['source'].reply(returned_msg)

			if command in self.search_cmds:
				if not q:
					q = msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:]
				if not q:
					return msg['source'].reply(u'nu ti zapross vvedi')
				try:
					if not offset:
						page = 1
					print u"page: %s, offset: %s, q: %s" % (page,offset,q)
					response = list(self.vkaudio.search(q.replace(u"\n",u" ")))
				except:
					try:
						response = list(self.vkaudio.search(q))
					except Exception as e:
						return msg['source'].reply(u'vk api error\n{}'.format(e))
				if not response:
					return msg['source'].reply(u'nichego ne nashel')
				self.search[(msg['source'].guild.id,msg['user_id'])] = (response,page,q)
				text = u'enter:\nretard magnitola <number>\n\nnum track /duration:\n'
				for track in response:
					try:
						text += u"{}: {} - {} /{}\n".format(response.index(track),track['artist'],track['title'],sectohum(seconds=int(track['duration'])))
					except Exception as error:
						text += u"{}: some error: {}\n".format(response.index(track),error)
					if len(text) > self.max_one_part_lenght:
						msg['source'].reply(text)
						text = u'enter:\nretard magnitola <number>\n\nnum track /duration:\n'

				return msg['source'].reply(text)
				
			if command in self.ytd_search_cmds:
				page = 1
				if not q:
					q = msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:]
				if not q:
					return msg['source'].reply(u'nu ti zapross vvedi, ebana')
				#ydl.extract_info('ytsearch5:vanomas dance', download=False, process=False)
				try:
					response = self.ydl.extract_info(u'ytsearch3:{}'.format(q.replace(u"\n",u" ")), download=False, process=False).get('entries',[])
				except Exception as e:
					return msg['source'].reply(u'ytd search error\n{}'.format(e))

				if not response:
					return msg['source'].reply(u'nichego ne nashel v youtube, my dude')

				ytd_response = response
				response = []
				for item in ytd_response:
					try:
						item_data = self.ydl.extract_info(item['id'], download=False, process=False)
						response.append({'url':item_data['formats'][0]['url'],'artist':item_data['uploader'],'duration':item_data['duration'],'title':item_data['title']})
					except Exception as error:
						print error
						pass
				ytd_response = []
				text = u'enter:\nretard magnitola <number>\n\nnum duration name:\n'
				for track in response:
					text += u'%02d: %s %s - %s\n' % (response.index(track),sectohum(seconds=int(track['duration'])),track['artist'],track['title'])
					
				self.search[(msg['source'].guild.id,msg['user_id'])] = (response,page,q)
				
				return self.cool_response(msg,text[:self.max_one_part_lenght],'numbers',len(response))
	
			if command in self.play_cmds + self.playplaylist_cmds:
				if direct_url:
					args = ['retard','m','p',direct_url]
				try:
					url = args[3]
				except:
					return msg['source'].reply(u'nu ti ssilku ukaji blya')
				try:
					int(url)
					msg['body'] = u'retard m {}'.format(url)
					return self.call(msg)
				except ValueError:
					pass
				if not direct_url:
					if msg['body'].count(u'!#') == 2:
						url = u'"{}"'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1+2:-2])

					if len(args[3:]) > 1 and not msg['body'].count(u'!#') == 2:
						msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
						return self.call(msg)						

					if not (u'.mp3' in url and u'#FILENAME/' in url):
						try:
							pre_cache_media = self.getmetadata(url)
							if not pre_cache_media:
								pre_cache = requests.get(url)
							else:
								pre_cache = FakeHeader()
								if pre_cache_media['stream'] and pre_cache_media['streams']:
									pre_cache = FakeHeaderStream()
						except IOError:
							msg['source'].reply(self.dc.markdown.blue(u'kakoe to govno ti kidaesh, dumau tebe stoit nayti oshibku v ssilke(probeli eblan), a poka popboruu mb cherez poisk nayti, chto ti kinul'))
							msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
							return self.call(msg)
						except UnicodeError:
							msg['source'].reply(self.dc.markdown.blue(u'kakoe to govno ti kidaesh, dumau tebe stoit nayti oshibku v ssilke(probeli eblan), a poka popboruu mb cherez poisk nayti, chto ti kinul...'))
							msg['body'] = u'retard m q {}'.format(msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:])
							return self.call(msg)
					else:
						direct_url = url.split(u'#FILENAME/')[0]
						duration = 0
						artist = u"Direct Url"
						title = u"Stream from VK"

				if direct_url:
					item = FFmpegInput(direct_url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = duration,artist = artist,title = title,respond=msg['source'].reply,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable)
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
						text += u'{}: {} {} - {}\n'.format(tracks.index(track),sectohum(seconds=int(track['duration'])),track['artist'],track['title'])
						self.get_player(msg['source'].guild.id)['player'].queue.append(FFmpegInput(track['url'],bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = track['duration'],artist=track['artist'],title=track['title'],respond=msg['source'].reply,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable))
						all_play_time += int(track['duration'])
						accept_tracks += 1

					text = u"Duration: {}\nTracks: {}\nPlaylist:\n".format(sectohum(seconds=all_play_time),accept_tracks) + text

					for text_frame in [text[i:i+self.max_one_part_lenght] for i in range(0,len(text),self.max_one_part_lenght)]:
						msg['source'].reply(self.dc.markdown.block(text_frame))
					return
				elif found_user_audio_page(url):
					try:
						tracks = list(self.vkaudio.get(int(found_user_audio_page(url)[0][1])))
					except Exception as error:
						return msg['source'].reply(u"vo vremya poluchenie tvoih audiozapiseye voznikla oshibochka\nskoree vsego y tebya:\n1)privatniy profil'\n2)zakriti zapisi\n3)oshibka servera\n\nerror:{}".format(error))
					###################################################
					max_tracks = 50
					text = u""
					for track in tracks:
						max_tracks -= 1
						if not max_tracks:
							try:
								msg['source'].reply(u'nu vpolne hvatit dlya nachala')
							except:
								pass
							break
						###############################################
						text += u'{}: {} {} - {}\n'.format(tracks.index(track),sectohum(seconds=int(track['duration'])),track['artist'],track['title'])
						self.get_player(msg['source'].guild.id)['player'].queue.append(FFmpegInput(track['url'],bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = track['duration'],artist=track['artist'],title=track['title'],respond=msg['source'].reply,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable))
					for text_frame in [text[i:i+self.max_one_part_lenght] for i in range(0,len(text),self.max_one_part_lenght)]:
						msg['source'].reply(self.dc.markdown.block(text_frame))
					return
				elif u'.mp3' in url and u'#FILENAME/' in url:
					msg['body'] = u'retard m p {}'.format(url.split(u'#FILENAME/')[0])
					return self.call(msg)
				elif u'.mp3' in url and pre_cache_media and pre_cache_media.get('size',0):
					if pre_cache_media.get('size',0) > 509715200:
						return msg['source'].reply(self.dc.markdown.blue(u'chta tvoya mp3 kakayata bolshaya kak tvoya mamka'))
					elif pre_cache_media.get('size',0) > 8192:
						item = FFmpegInput(url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration=pre_cache_media.get('duration'),artist = pre_cache_media.get('artist'),title=pre_cache_media.get('title'),filesize=pre_cache_media.get('size'),respond=msg['source'].reply,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable)
					else:
						return msg['source'].reply(self.dc.markdown.blue(u'chta tvoya mp3 kakayata malenkaya'))
				elif pre_cache.headers.get('Content-Type') == 'AudioStream':
					item = FFmpegInput(url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = 0,artist = 'Audio',title = 'Stream',filesize = 0,respond=msg['source'].reply,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable)
				else:
					if len(url) < 2:
						return msg['source'].reply(u'ti pidoras ili huesos?.')

					if command in self.playplaylist_cmds:
						playlist_source = True
					else:
						playlist_source = False

					try:
						if playlist_source:
							ytd = self.ydl_pl.extract_info(url, download=False, process=False)
						else:
							ytd = self.ydl.extract_info(url, download=False, process=False)
					except youtube_dl.utils.DownloadError:
						q = msg['body'][len(args[0])+1+len(args[1])+1+len(args[2])+1:]
						print q
						msg['body'] = u'retard m q {}'.format(q)
						if len(q.split()) > 1:
							msg['source'].reply(self.dc.markdown.blue(u"naverno stoit tebe napomnit', chto poisk cherez drugui komandu..."))
							return self.call(msg)
						else:
							if 'http' in q:
								return msg['source'].reply(self.dc.markdown.blue(u"skoree vsego ti kinul ssilku, tak vot ebanat... ti blya hot' posmotri na nee.. ee daje ydl ne hochet parsit'... tam nepos blya ti ee cherez poisk ili druguu zalupu kinul... pochisti ee i skin' zanogo"))
							else:
								return self.call(msg)
					except Exception as e:
						return msg['source'].reply(u'Unknown source///\n\n Have error:\n{}\n\n///Url: {}'.format(e,url))
					entries_pack = False
					text = u''
					count_ent = 0

					if 'entries' in ytd and ytd['entries'] and playlist_source:
						if msg['user_id'] in self.wait_playlist:
							return msg['source'].reply(u'padaji ebana.... ya esche proshliy playlist ne sdelal')

						try:
							self.wait_playlist[msg["user_id"]] = 0
							msg['source'].reply(u"padaji ebana nemnogo, gruzim playlist...\n\ntips:\nesli muzika tak i ne zaigrala spustya daje 10 secund, naverno playlist yavlyatsya lutoy huyney i ne hochet gruzit'sya... togda vstavlyay ssilki po odnoy, chtob navernika")
							for entries in ytd['entries']:
								if not msg['source'].guild.id in self.guilds:
									return msg['source'].reply(u"ti ebanutiy?? nahuya takoy dlinniy kidat' gaylist blya, a potom delat' tak,chtob ya livnul???")
								count_ent += 1
								try:
									track = self.ydl.extract_info(entries['url'], download=False, process=False)
									text += u'{}: {} {} - {}\n'.format(count_ent,sectohum(seconds=int(track.get('duration',0))),track.get('uploader',"Unknown Uploader"),track.get('title','Unknown Title'))
									self.get_player(msg['source'].guild.id)['player'].queue.append(FFmpegInput(track['formats'][0]['url'],bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = int(track.get('duration',0)),artist=track.get('uploader',"Unknown Uploader"),title=track.get('title','Unknown Title'),respond=msg['source'].reply,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable))
								except Exception as e:
									text += u'{} - SKIPPED HAVE ERROR: {}\n'.format(count_ent,e)
									
								if len(text) > self.max_one_part_lenght:
									msg['source'].reply(self.dc.markdown.block(text[:self.max_one_part_lenght]))
									text = u""

								#entries_pack = True
							if entries_pack:
								for text_frame in [text[i:i+self.max_one_part_lenght] for i in range(0,len(text),self.max_one_part_lenght)]:
									msg['source'].reply(self.dc.markdown.block(text_frame))

							return
						finally:
							if msg['user_id'] in self.wait_playlist:
								del self.wait_playlist[msg["user_id"]]
					################################################################
					#print ytd
					if 'formats' in ytd and ytd['formats']:
						url = ytd['formats'][0]['url']
						if ytd.get("is_live",False) and ytd['formats'][0].get('protocol',None) == u'm3u8':
							#print 'live'
							live_stream_url = True
					else:
						try:
							msg['body'] = u"retard m p {}".format(ytd['url'])
						except KeyError:
							return msg['source'].reply(u'skoree vsego ti skinul playlist ne s vk, a s drugogo resursa, pojaluysta vospolzuysya drugoy commandoy a imenno:\nretard m ppl {}'.format(url))
							
						return self.call(msg)
						#return msg['source'].reply(u'y tebya bitaya ssilka,libo ti ebat kakoy retard..... chto kidaesh huevuy ssilku')
					################################################################
					duration = ytd.get('duration',0)
					try:
						title = ytd.get('title','Unknown Title')
					except:
						title = u'From unknown YTD'
					try:
						artist = ytd.get('uploader',"Unknown Uploader")
					except:
						artist = u'YTD unknown uploader'
					item = FFmpegInput(url,bass = bass_count,user_id=msg['user_id'],channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = duration,artist = artist,title = title,filesize = ytd.get('size',0),respond=msg['source'].reply,live_stream = live_stream_url,abdulov = abdulov,replay = replay).pipe(BufferedOpusEncoderPlayable)

				if self.get_player(msg['source'].guild.id).get('player',False):
					self.get_player(msg['source'].guild.id)['player'].queue.append(item)
				else:
					self.dc.bans.add_user(msg['user_id'],'ebu metko i konkretno... (spam ddos:not create player)'.format(msg['body']))
					return
				if puten:
					#
					self.get_player(msg['source'].guild.id)['player'].queue.append(FFmpegInput(u'./content/putin.mp3',bass = bass_count,user_id=0,channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = 3,artist = 'putin',title = 'your god',filesize = 0,respond=None, broadcast = False, local_file = True).pipe(BufferedOpusEncoderPlayable))
					#
				if self.get_player(msg['source'].guild.id)['player'].already_play:
					return self.cool_response(msg,u'nu chtoj rvi dushu sanya...\n tvoe mesto v ocheredi, vrode kak: %s\n_______________________________\n|   ЕБЛАН ТУПОЙ ИСПОЛЬЗУЙ  |\n|   ЭТИ КНОПКИ СНИЗУ БЛЯТЬ  |' % len(self.guilds[msg['source'].guild.id]['player'].queue),'play')
				else:
					return

			if command in self.now_cmds:
				if msg['source'].guild.id in self.guilds:
					try:
						current = self.get_player(msg['source'].guild.id)['player'].now_playing.source
						current.respond(u"""
Now playing: {} - {}
Played: {}/{}
Request: <@{}>
""".format(current.artist,current.title,sectohum(seconds=int(current.played)),sectohum(seconds=int(current.duration)),current.user_id))
						current = None
						return
					except AttributeError:
						return msg['source'].reply(u'nihuya net igraet sha, infa sotka')
				else:
					return msg['source'].reply(u'tak ya nichego ne igrau')

			if command in self.playlist_cmds:
				if msg['source'].guild.id in self.guilds:
					try:
						text = u"Playlist:\n"
						if self.get_player(msg['source'].guild.id)['player'].queue._data:
							nums_track = 0
							for item in self.get_player(msg['source'].guild.id)['player'].queue._data:
								nums_track += 1
								try:
									text += u"""
{}: {} - {}, {}
request: <@{}>
""".format(self.get_player(msg['source'].guild.id)['player'].queue._data.index(item),item.source.artist,item.source.title, sectohum(seconds=int(item.source.duration)),item.source.user_id)
								except Exception as error:
									text += u"\nTrack: {}. Have parse error: {}\n".format(nums_track,error)
							return msg['source'].reply(text[:self.max_one_part_lenght])
						else:
							return msg['source'].reply(u"playlist pustoy((")
					except AttributeError:
						return msg['source'].reply(u'nihuya net igraet sha i ne budet igrat, infa sotka')
				else:
					return msg['source'].reply(u'tak ya nichego ne igrau i ne budu igrat')
	
			if command in self.pause_cmds:
				return msg['source'].reply(u'ha net... ne budu etogo delat')
				if msg['source'].guild.id in self.guilds:
					try:
						self.get_player(msg['source'].guild.id)['player'].pause()
					except AttributeError:
						return msg['source'].reply(u'nihuya net igraet sha, infa sotka')
					return msg['source'].reply(u'jdem, poka ti razrodishsya')
				else:
					return msg['source'].reply(u'tak ya nichego ne igrau')

			if command in self.replay_cmds:
				return msg['source'].reply(u'not working')
				if self.guilds[msg['source'].guild.id]['player'].replay:
					self.guilds[msg['source'].guild.id]['player'].replay = False
					return msg['source'].reply(u'replay vikluchen:off')
				else:
					self.guilds[msg['source'].guild.id]['player'].replay = True
					return msg['source'].reply(u'replay vkluchen:on')

			if command in self.change_text_channel_cmds:
				channel = args[3] if len(args) > 3 else None
				if not channel:
					return msg['source'].reply(u'nu ti kanal ukaji')

				cid = channel.split('<#')[1][:-1] if '<#' in channel[:2] and '>' in channel[-1:] else None
				if not cid:
					return msg['source'].reply(u'nu ti ego ebat pravilnom formate ukaji\n p.s #channelname')

				cid = int(cid)
				if not cid in msg['source'].guild.channels.keys():
					return msg['source'].reply(u'na servere net kanala s takim id')

				if msg['source'].guild.channels[cid].is_voice:
					return msg['source'].reply(u'da blyat govorit naverno ya budu tuda, da???? ukaji texoviy')

				self.guilds[msg['source'].guild.id]['player'].text_id = cid
				return msg['source'].reply(u'set... player info sending msg in <#{}> channel'.format(cid))


			if command in self.resume_cmds:
				return msg['source'].reply(u'ha net... ne budu etogo delat)')
				if msg['source'].guild.id in self.guilds:
					try:
						self.get_player(msg['source'].guild.id)['player'].resume()
					except AttributeError:
						return msg['source'].reply(u'nihuya net igraet sha, infa sotka')
					return msg['source'].reply(u'rvem dushu')
				else:
					return msg['source'].reply(u'tak ya nichego ne igrau')

			if command in self.stop_cmds:
				if msg['source'].guild.id in self.guilds:
					try:
						self.get_player(msg['source'].guild.id)['player'].now_playing.source.user_id
					except:
						
						return self.cool_response(msg,'nihuya net igraet sha, infa sotka','play')

					if msg['user_id'] == self.get_player(msg['source'].guild.id)['player'].now_playing.source.user_id:
						try:
							self.get_player(msg['source'].guild.id)['player'].skip()
							if not self.get_player(msg['source'].guild.id)['player'].queue._data:
								return self.cool_response(msg,u'lana','play')
						except Exception as e:
							return msg['source'].reply(u'nihuya net igraet sha, infa sotka\na na dele:{}'.format(e))
					#############################################################################################################
					try:
						leaved_user = not msg['source'].guild.get_voice_state(msg['source'].guild.get_member(self.get_player(msg['source'].guild.id)['player'].now_playing.source.user_id))
					except:
						leaved_user = True#new disco version fix
					#############################################################################################################
					if leaved_user:
						try:
							self.get_player(msg['source'].guild.id)['player'].skip()
							if not self.get_player(msg['source'].guild.id)['player'].queue._data:
								return self.cool_response(msg,u'lana, ibo etot loh ushel(tot korotiy postavil eto govno)','play')
						except Exception as e:
							return msg['source'].reply(u'nihuya net igraet sha, infa sotka\na na dele:{}'.format(e))
					else:
						if msg['user_id'] in self.get_player(msg['source'].guild.id)['player'].now_playing.source.vote_users:
							return msg['source'].reply(u'ti uje progolosoval')
						else:
							if randint(1,3) == 1:
								self.get_player(msg['source'].guild.id)['player'].queue._data = [FFmpegInput(u'./content/naeb_swiney.mp3',bass = bass_count,user_id=0,channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = 3,artist = 'margo',title = 'vote skip',filesize = 0,respond=None, broadcast = False, local_file = True).pipe(BufferedOpusEncoderPlayable)] + self.get_player(msg['source'].guild.id)['player'].queue._data
								self.get_player(msg['source'].guild.id)['player'].skip()
								return msg['source'].reply(u'iiiiiiiiiiiiiiiiiiiiiii naebali swiney!')
							######################################################################################################
							self.get_player(msg['source'].guild.id)['player'].now_playing.source.vote_users.append(msg['user_id'])
						
						need_votes = 0
						channels = {}
						for states in six.itervalues(msg['source'].guild.voice_states):
							#if states.user_id == self.get_player(msg['source'].guild.id)['player'].now_playing.source.user_id:
							#	need_votes -= 1
							if True:
								if states.channel_id in channels:
									channels[states.channel_id].append(states.user_id)
								else:
									channels[states.channel_id] = [states.user_id]
							
						if voice_channel_id in channels and len(channels[voice_channel_id]) == 1:
							return msg['source'].reply(u'petuham prava golosa ne davali')

						if my_voice_channel_id and my_voice_channel_id in channels and voice_channel_id in channels:
							need_votes = len(channels[voice_channel_id]) - 2

						if not need_votes and len(channels[voice_channel_id]) > 2:
							need_votes = len(channels[voice_channel_id]) - 1

						need_votes = need_votes / 2

						if len(self.get_player(msg['source'].guild.id)['player'].now_playing.source.vote_users) >= need_votes:
							self.get_player(msg['source'].guild.id)['player'].queue._data = [FFmpegInput(u'./content/vote_end.mp3',bass = bass_count,user_id=0,channel_id=voice_channel_id,guild_id=msg['source'].guild.id,duration = 3,artist = 'counter strike',title = 'vote end',filesize = 0,respond=None, broadcast = False, local_file = True).pipe(BufferedOpusEncoderPlayable)] + self.get_player(msg['source'].guild.id)['player'].queue._data
							self.get_player(msg['source'].guild.id)['player'].skip()
							if not self.get_player(msg['source'].guild.id)['player'].queue._data:
								return msg['source'].reply(u'lana, tak uj poshlo')
						else:
							return self.cool_response(msg,u'nujno esche {} golosov'.format(need_votes - len(self.get_player(msg['source'].guild.id)['player'].now_playing.source.vote_users)),'play')
					if not self.get_player(msg['source'].guild.id)['player'].queue._data:
						return msg['source'].reply(u'lana')
				else:
					
					return self.cool_response(msg,u'tak ya nichego ne igrau','play')	
			else:
				return self.cool_response(msg,helper)
		except Exception as e:
			return self.dc.DISCORD_CORE.error_report(text=msg['body'], error=e, traceinfo=traceback.format_exc())
