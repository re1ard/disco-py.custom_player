import time
import gevent

from holster.enum import Enum
from holster.emitter import Emitter

from disco.voice.client import VoiceState
from disco.voice.queue import PlayableQueue
from disco.util.logging import LoggingClass

from datetime import timedelta as sectohum
from websocket import WebSocketConnectionClosedException


class Player(LoggingClass):
    Events = Enum(
        'START_PLAY',
        'STOP_PLAY',
        'PAUSE_PLAY',
        'RESUME_PLAY',
        'DISCONNECT',
    )

    def __init__(self, client, queue=None):
        super(Player, self).__init__()
        self.client = client

	self.last_activity = time.time()

	self.force_kick = False

	self.already_play = False

	self.force_return = 1
	self.max_returns = 1
	self.sleep_time_returns = 30

        # Queue contains playable items
        self.queue = queue or PlayableQueue()

        # Whether we're playing music (true for lifetime)
        self.playing = True

        # Set to an event when playback is paused
        self.paused = None

        # Current playing item
        self.now_playing = None

        # Current play task
        self.play_task = None

        # Core task
        self.run_task = gevent.spawn(self.run)

        # Event triggered when playback is complete
        self.complete = gevent.event.Event()

        # Event emitter for metadata
        self.events = Emitter()

    def disconnect(self):
        self.client.disconnect()
        self.events.emit(self.Events.DISCONNECT)

    def skip(self):
	if self.now_playing and self.now_playing.source:
		self.now_playing.source.killed()
	else:
		print u'source have unknown type???'


    def pause(self):
        if self.paused:
            return
        self.paused = gevent.event.Event()
        self.events.emit(self.Events.PAUSE_PLAY)

    def resume(self):
        if self.paused:
            self.paused.set()
            self.paused = None
            self.events.emit(self.Events.RESUME_PLAY)

    def play(self, item):
        # Grab the first frame before we start anything else, sometimes playables
        #  can do some lengthy async tasks here to setup the playable and we
        #  don't want that lerp the first N frames of the playable into playing
        #  faster
        frame = item.next_frame()
        if frame is None:
            return

        start = time.time()
        loops = 0

	if item.source.need_alarm:
		#item.source.respond(embed = item.source.embed)
		gevent.spawn(item.source.respond,embed = item.source.embed)

        while True:
            loops += 1

            if self.paused:
                self.client.set_speaking(False)
                self.paused.wait()
                gevent.sleep(2)
                self.client.set_speaking(True)
                start = time.time()
                loops = 0

            if self.client.state == VoiceState.DISCONNECTED:
                return

            if self.client.state != VoiceState.CONNECTED:
                self.client.state_emitter.once(VoiceState.CONNECTED, timeout=30)

            # Send the voice frame and increment our timestamp
	    try:
            	self.client.send_frame(frame)
            	self.client.increment_timestamp(item.samples_per_frame)
	    	self.client.set_speaking(True)
	    except WebSocketConnectionClosedException as error:
		print "WS Error: {}, gid: {}".format(error,self.client.channel.guild_id)
		self.client.set_state(VoiceState.DISCONNECTED)
		while self.force_return and item.source.proc_working:
			print "gid: {}, try number: {}, connect to WebSocket".format(self.client.channel.guild_id,self.max_returns)
			self.max_returns += 1
			try:
				self.client.connect(timeout = 60)
				self.max_returns = 0
				break
			except Exception as error:
				print "gid: {}, connect error: {}, sleep...".format(self.client.channel.guild_id,error)
				gevent.sleep(self.sleep_time_returns)

	    # Check proc live
	    if not item.source.proc_working:
		self.client.set_speaking(False)
		return

	    # Get next
            frame = item.next_frame()
	    self.last_activity = time.time()
            if frame is None:
		self.client.set_speaking(False)
		if item.source:
			item.source.proc_working = False
                return

            next_time = start + 0.02 * loops
            delay = max(0, 0.02 + (next_time - time.time()))
	    item.source.played += delay
            gevent.sleep(delay)

    def run(self):
        #self.client.set_speaking(True)

        while self.playing:
            self.now_playing = self.queue.get()

            self.events.emit(self.Events.START_PLAY, self.now_playing)
            self.play_task = gevent.spawn(self.play, self.now_playing)

	    self.already_play = True
	    self.last_activity = time.time()

            self.play_task.join()
            self.events.emit(self.Events.STOP_PLAY, self.now_playing)

	    if self.now_playing and self.now_playing.source:
	    	self.now_playing.source.proc_working = False
	    self.already_play = False


            if self.client.state == VoiceState.DISCONNECTED:
                self.playing = False
                self.complete.set()
                return

        self.client.set_speaking(False)
        self.disconnect()
