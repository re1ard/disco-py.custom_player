import abc
import six
import types
import gevent
import struct
import subprocess
import youtube_dl

from gevent.lock import Semaphore
from gevent.queue import Queue

from disco.voice.opus import OpusEncoder
from disco.types.message import MessageEmbed
from datetime import timedelta as sectohum
from time import time,strftime,localtime

try:
    from cStringIO import cStringIO as BufferedIO
except ImportError:
    if six.PY2:
        from StringIO import StringIO as BufferedIO
    else:
        from io import BytesIO as BufferedIO


OPUS_HEADER_SIZE = struct.calcsize('<h')


class AbstractOpus(object):
    def __init__(self, sampling_rate=48000, frame_length=20, channels=2):
        self.sampling_rate = sampling_rate
        self.frame_length = frame_length
        self.channels = 2
        self.sample_size = 2 * self.channels
        self.samples_per_frame = int(self.sampling_rate / 1000 * self.frame_length)
        self.frame_size = self.samples_per_frame * self.sample_size


class BaseUtil(object):
    def pipe(self, other, *args, **kwargs):
        child = other(self, *args, **kwargs)
        setattr(child, 'metadata', self.metadata)
        setattr(child, '_parent', self)
        return child

    @property
    def metadata(self):
        return getattr(self, '_metadata', None)

    @metadata.setter
    def metadata(self, value):
        self._metadata = value


@six.add_metaclass(abc.ABCMeta)
class BasePlayable(BaseUtil):
    @abc.abstractmethod
    def next_frame(self):
        raise NotImplementedError


@six.add_metaclass(abc.ABCMeta)
class BaseInput(BaseUtil):
    @abc.abstractmethod
    def read(self, size):
        raise NotImplementedError

    @abc.abstractmethod
    def fileobj(self):
        raise NotImplementedError


class OpusFilePlayable(BasePlayable, AbstractOpus):
    """
    An input which reads opus data from a file or file-like object.
    """
    def __init__(self, fobj, *args, **kwargs):
        super(OpusFilePlayable, self).__init__(*args, **kwargs)
        self.fobj = fobj
        self.done = False

    def next_frame(self):
        if self.done:
            return None

        header = self.fobj.read(OPUS_HEADER_SIZE)
        if len(header) < OPUS_HEADER_SIZE:
            self.done = True
            return None

        data_size = struct.unpack('<h', header)[0]
        data = self.fobj.read(data_size)
        if len(data) < data_size:
            self.done = True
            return None

        return data


class FFmpegInput(BaseInput, AbstractOpus):
    def __init__(self, source='-', command='avconv', streaming=False, bass=0, user_id = 0, channel_id = 0 ,guild_id = 0, duration = 0, artist = 0, title = 0, filesize = 0, respond = unicode, need_alarm = True, live_stream = False, abdulov = False, local_file = False, executer = None, **kwargs):
        super(FFmpegInput, self).__init__(**kwargs)
        if source:
            self.source = source

        self.streaming = streaming
        self.command = command
	self.bass = bass
	self.user_id = user_id
	self.channel_id = channel_id
	self.guild_id = guild_id
	self.duration = duration
	self.artist = artist
	self.title = title
	self.filesize = filesize
	self.respond = respond
	self.played = 0.0
	self.vote_users = []
	self.need_alarm = need_alarm
	self.live_stream = live_stream
	self.abdulov = abdulov
	self.local_file = local_file
	self.executer = executer

        self._buffer = None
        self._proc = None
	self.stream = 1
	self.proc_working = False
	
	self.build_embed()

	self.error_embed = MessageEmbed()
	self.error_embed.set_author(name = u'Retarded Magnitola Play Error Header',icon_url = u'https://pp.userapi.com/c846021/v846021803/6924d/jYvIcO1FU2k.jpg')
	self.error_embed.title = u'FFMPEG returned error'
	self.error_embed.set_footer(text='Powered RetardBot Engine | https://discord.gg/tG35Y4b | gsd#6615')

	self.build_cmd()

    def build_embed(self):
	self.embed = MessageEmbed()
	self.embed.set_author(name = u'Retarded Magnitola', url=u'https://vk.cc/7kdHoP',icon_url = u'https://pp.userapi.com/c836336/v836336785/1ec0a/Utfj9j7yfSI.jpg')
	self.embed.title = u'Now play:'
	self.embed.url = self.source
	self.embed.add_field(name = u'Time:', value = u'{}'.format(sectohum(seconds=int(self.duration))),inline=True)
	self.embed.add_field(name = u'Bass:', value = u'{} dB'.format(self.bass),inline=True)
	self.embed.add_field(name = u'Request:', value = u'<@!{}>'.format(self.user_id),inline=True)
	self.embed.add_field(name = u'Channel:', value = u'<#{}>'.format(self.channel_id))
	self.embed.description = u'Title: {}\nAuthor: {}'.format(self.title,self.artist)
	self.embed.set_footer(text='Powered RetardBot Engine | https://discord.gg/tG35Y4b | gsd#6615')
	return True

    def build_cmd(self,source = None,use_executer = False):
	self.cmd_args = []
	if not source:
		source = self.source
	if use_executer:
		try:
			track = use_executer(source,download=False, process=False)
		except Exception as e:
			return True	

	if not self.live_stream:
		if self.local_file:
			self.cmd_args = [
				self.command,
				'-i', str(source)
				]
		else:
			self.cmd_args = [
				self.command,
				'-reconnect', '1',
				'-reconnect_at_eof', '1',
				'-reconnect_streamed', '1',
				'-reconnect_delay_max', '3000',
				'-i', str(source)
				]
			
	else:
		self.cmd_args = [
			"python",
			"./stream_support.py", 
			source
			]

	self.cmd_args += [
			'-vn',
			'-f','s16le',
			'-ar', str(self.sampling_rate),
			'-ac', str(self.channels),
			'-af','bass=g={}'.format(self.bass)
			]


	if self.abdulov:
		self.cmd_args[len(self.cmd_args)-1] += ",rubberband=pitch=0.8,rubberband=tempo=1.2,volume=1.5"

	self.cmd_args += [
			'-loglevel', 'error',
			'pipe:1'
			]

	return True

    def read(self,sz):
	return self.proc.stdout.read(sz)

    def killed(self):
	self.stream = 0
	self.proc_working = False
	self.proc.kill()
	return True

    def fileobj(self):
        if self.streaming:
            return self.proc.stdout
        else:
            return self

    @property
    def proc(self):
        if not self._proc:
            if callable(self.source):
                self.source = self.source(self)

            if isinstance(self.source, (tuple, list)):
                self.source, self.metadata = self.source
	
	    #if self.executer:
		#self.build_cmd

	    self._proc = subprocess.Popen(self.cmd_args,bufsize = 81920, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	    self.proc_working = True
	    self.embed.add_field(name = u'Start Playing:', value = strftime("%H:%M:%S", localtime(time())),inline=True)
	    print u"Now in {}.{} playing {} - {}, {} sec, request from {}. File size: {} Mb. PID: {}".format(self.guild_id,self.channel_id,self.artist,self.title,self.duration,self.user_id,self.filesize/1024/1024,self.proc.pid)
        return self._proc

class BufferedOpusEncoderPlayable(BasePlayable, OpusEncoder, AbstractOpus):
    def __init__(self, source, *args, **kwargs):
        self.source = source
        #self.frames = Queue(kwargs.pop('queue_size', 4096))

        # Call the AbstractOpus constructor, as we need properties it sets
        AbstractOpus.__init__(self, *args, **kwargs)

        # Then call the OpusEncoder constructor, which requires some properties
        #  that AbstractOpus sets up
        OpusEncoder.__init__(self, self.sampling_rate, self.channels)

    def next_frame(self):
	raw = self.source.read(self.frame_size)
	if len(raw) < self.frame_size:
		try:
			have_error = self.source.proc.stderr.read()
			if have_error and self.source.stream and self.source.respond:
				self.source.error_embed.description = have_error
				self.source.error_embed.add_field(name = u'Last played time:', value = u'{}'.format(sectohum(seconds=int(self.source.played))),inline=True)
				gevent.spawn(self.source.respond,embed = self.source.error_embed)
		except Exception as error:
			print error
		self.source.killed()
		self.source._proc = None
		self.source._buffer = None
		self.source = None
		return None
	return self.encode(raw, self.samples_per_frame)


class DCADOpusEncoderPlayable(BasePlayable, AbstractOpus, OpusEncoder):
    def __init__(self, source, *args, **kwargs):
        self.source = source
        self.command = kwargs.pop('command', 'dcad')
        self.on_complete = kwargs.pop('on_complete', None)
        super(DCADOpusEncoderPlayable, self).__init__(*args, **kwargs)

        self._done = False
        self._proc = None

    @property
    def proc(self):
        if not self._proc:
            source = obj = self.source.fileobj()
            if not hasattr(obj, 'fileno'):
                source = subprocess.PIPE

            self._proc = subprocess.Popen([
                self.command,
                '--channels', str(self.channels),
                '--rate', str(self.sampling_rate),
                '--size', str(self.samples_per_frame),
                '--bitrate', '128',
                '--fec',
                '--packet-loss-percent', '30',
                '--input', 'pipe:0',
                '--output', 'pipe:1',
            ], stdin=source, stdout=subprocess.PIPE)

            def writer():
                while True:
                    data = obj.read(2048)
                    if len(data) > 0:
                        self._proc.stdin.write(data)
                    if len(data) < 2048:
                        break

            if source == subprocess.PIPE:
                gevent.spawn(writer)
        return self._proc

    def next_frame(self):
        if self._done:
            return None

        header = self.proc.stdout.read(OPUS_HEADER_SIZE)
        if len(header) < OPUS_HEADER_SIZE:
            self._done = True
            self.on_complete()
            return

        size = struct.unpack('<h', header)[0]

        data = self.proc.stdout.read(size)
        if len(data) < size:
            self._done = True
            self.on_complete()
            return

        return data


class FileProxyPlayable(BasePlayable, AbstractOpus):
    def __init__(self, other, output, *args, **kwargs):
        self.flush = kwargs.pop('flush', False)
        self.on_complete = kwargs.pop('on_complete', None)
        super(FileProxyPlayable, self).__init__(*args, **kwargs)
        self.other = other
        self.output = output

    def next_frame(self):
        frame = self.other.next_frame()

        if frame:
            self.output.write(struct.pack('<h', len(frame)))
            self.output.write(frame)

            if self.flush:
                self.output.flush()
        else:
            self.output.flush()
            self.on_complete()
            self.output.close()
        return frame


class PlaylistPlayable(BasePlayable, AbstractOpus):
    def __init__(self, items, *args, **kwargs):
        super(PlaylistPlayable, self).__init__(*args, **kwargs)
        self.items = items
        self.now_playing = None

    def _get_next(self):
        if isinstance(self.items, types.GeneratorType):
            return next(self.items, None)
        return self.items.pop()

    def next_frame(self):
        if not self.items:
            return

        if not self.now_playing:
            self.now_playing = self._get_next()
            if not self.now_playing:
                return

        frame = self.now_playing.next_frame()
        if not frame:
            return self.next_frame()

        return frame


class MemoryBufferedPlayable(BasePlayable, AbstractOpus):
    def __init__(self, other, *args, **kwargs):
        from gevent.queue import Queue

        super(MemoryBufferedPlayable, self).__init__(*args, **kwargs)
        self.frames = Queue()
        self.other = other
        gevent.spawn(self._buffer)

    def _buffer(self):
        while True:
            frame = self.other.next_frame()
            if not frame:
                break
            self.frames.put(frame)
        self.frames.put(None)

    def next_frame(self):
        return self.frames.get()
