import time
import gevent

from datetime import timedelta as sectohum

from holster.enum import Enum
from holster.emitter import Emitter

from disco.voice.client import VoiceState
from disco.voice.queue import PlayableQueue

MAX_TIMESTAMP = 4294967295


class Player(object):
    Events = Enum(
        'START_PLAY',
        'STOP_PLAY',
        'PAUSE_PLAY',
        'RESUME_PLAY',
        'DISCONNECT'
    )

    def __init__(self, client, queue=None):
        self.client = client

	self.last_activity = time.time()

	self.force_kick = False

	self.already_play = False

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
        self.events = Emitter(gevent.spawn)

    def disconnect(self):
        self.client.disconnect()
        self.events.emit(self.Events.DISCONNECT)

    def skip(self):
	self.now_playing.source.killed()

    def pause(self):
        if self.paused:
            return
        self.paused = gevent.event.Event()
        self.events.emit(self.Events.PAUSE_PLAY)

    def resume(self):
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
                self.client.state_emitter.wait(VoiceState.CONNECTED)

            self.client.send_frame(frame)
            self.client.timestamp += item.samples_per_frame
            if self.client.timestamp > MAX_TIMESTAMP:
                self.client.timestamp = 0

            frame = item.next_frame()
            if frame is None:
                return

            next_time = start + 0.02 * loops
            delay = max(0, 0.02 + (next_time - time.time()))
	    item.source.played += delay
            gevent.sleep(delay)

    def run(self):
        self.client.set_speaking(True)

        while self.playing:
            self.now_playing = self.queue.get()
	    self.already_play = True
            self.events.emit(self.Events.START_PLAY, self.now_playing)
            self.play_task = gevent.spawn(self.play, self.now_playing)

	    self.now_playing.source.respond(u"""
:radio: Teper igraete komposiciya: {}, avtora {}
:stopwatch: idet dannaya muzika {}.

:chicken: Zakazal etu govninu <@{}>
:performing_arts: Igraet v anale <@{}>
:gear: Bass raven {} dB.
""".format(self.now_playing.source.title,self.now_playing.source.artist,sectohum(seconds=int(self.now_playing.source.duration)),self.now_playing.source.user_id,self.now_playing.source.channel_id,self.now_playing.source.bass))

            self.play_task.join()
            self.events.emit(self.Events.STOP_PLAY, self.now_playing)
	    self.already_play = False
	    self.last_activity = time.time()

            if self.client.state == VoiceState.DISCONNECTED:
                self.playing = False
                self.complete.set()
                return

        self.client.set_speaking(False)
        self.disconnect()
