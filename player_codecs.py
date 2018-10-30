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
        def __init__(self,source = "",**kwargs):

                #for key,data in kwargs.items():
                #        setattr(self,key,data)
                        
                super(FFmpegInput, self).__init__()
                self.command = "ffmpeg"
                self.source = source

                for key,data in kwargs.items():
                        setattr(self,key,data)

                self.about = {}
                for key in [u"pid",u"guild_id",u"channel_id",u"user_id",u"artist",u"title",u"duration",u"filesize_mb"]:
                        self.about.update({key:getattr(self,key,None)})
                
                try:
                        self.about['filesize_mb'] = getattr(self,u'filesize',0) / 1024 / 1024
                except:
                        self.about['filesize_mb'] = 0

                for key in self.about.keys():
                        try:
                                if type(self.about[key]) in [int,bool]:
                                        self.about[key] = unicode(self.about[key])
                                elif type(self.about[key]) in [str]:
                                        self.about[key] = unicode(self.about[key],"utf-8")
                                else:
                                        self.about[key] = unicode(self.about[key])
                        except Exception as error:
                                self.about[key] = u"{}".format(error)

                self.process = None
                self.stream = 1
                self.proc_working = False
                self.played = 0.0
                self.vote_users = []
                self.error = None
                
                self.build_embed()
                self.build_error_embed()
                self.cmd_args = self.build_cmd()

        def build_error_embed(self):
                self.error_embed = MessageEmbed()
                self.error_embed.set_author(name = u'Retarded Magnitola Play Error Header',icon_url = u'https://cdn.discordapp.com/attachments/499206696657223680/499206822045941780/run.gif')
                self.error_embed.title = u'FFMPEG returned error'
                self.error_embed.set_footer(text='Powered RetardBot Engine | https://discord.gg/tG35Y4b | gsd#6615')
                return True

        def build_embed(self):
                self.embed = MessageEmbed()
                self.embed.set_author(name = u'Retarded Magnitola', url=u'https://vk.cc/7kdHoP',icon_url = u'https://cdn.discordapp.com/attachments/499206696657223680/499206798851440641/kekbi.gif')
                self.embed.title = u'Now play:'
                self.embed.url = self.source
                self.embed.add_field(name = u'Time:', value = u'{}'.format(sectohum(seconds=int(self.duration))),inline=True)
                self.embed.add_field(name = u'Bass:', value = u'{} dB'.format(self.bass.value),inline=True)
                self.embed.add_field(name = u'Request:', value = u'<@!{}>'.format(self.user_id),inline=True)
                self.embed.add_field(name = u'Channel:', value = u'<#{}>'.format(self.channel_id),inline=True)
                self.embed.add_field(name = u'Replay:', value = u'{}'.format(getattr(self,"replay",False)),inline=True)
                self.embed.description = u'Title: {}\nAuthor: {}'.format(self.title,self.artist)
                self.embed.set_footer(text='Powered RetardBot Engine | https://discord.gg/tG35Y4b | gsd#6615')
                return True

        def build_cmd(self):
                player_args = []
                net_source_args = ['-reconnect','1','-reconnect_at_eof', '1','-reconnect_streamed','1','-reconnect_delay_max','3000']
                other_args = ['-vn','-f','s16le','-ar', getattr(self,"sampling_rate",48000),'-ac', getattr(self,"channels",2),'-af','bass=g={}'.format(getattr(getattr(self,"bass",None),"value",0))]
                if getattr(self,u"live_stream",False):
                        player_args.append(u"python")
                        player_args.append(u"./stream_support.py")
                        player_args.append(self.source)
                else:
                        player_args.append(self.command)

                        if getattr(self,u"replay",False):
                                player_args.append(u"-stream_loop")
                                player_args.append(u"-1")

                        if not getattr(self,u"local_file",False):
                                player_args += net_source_args
                        
                        player_args.append(u"-i")
                        player_args.append(self.source)

                player_args += other_args
                if getattr(self,"abdulov",False):
                        player_args[len(player_args)-1] += ",rubberband=pitch=0.8,rubberband=tempo=1.2,volume=1.5"
                player_args.append("-loglevel")
                player_args.append("error")
                player_args.append("pipe:1")
                return [str(i) for i in player_args]

        def killed(self):
                self.stream = 0
                self.proc_working = False
                try:
                        self.process.kill()
                except:
                        pass

                return True

        def read(self,chunk_size = 4096):
                return self.process.stdout.read(chunk_size)

        def fileobj(self):
                if getattr(self,"streaming",False):
                        return self.process.stdout
                else:
                        return self

class BufferedOpusEncoderPlayable(BasePlayable, OpusEncoder, AbstractOpus):
    def __init__(self, source, *args, **kwargs):
        self.source = source
        #self.frames = Queue(kwargs.pop('queue_size', 4096))

        # Call the AbstractOpus constructor, as we need properties it sets
        AbstractOpus.__init__(self, *args, **kwargs)

        # Then call the OpusEncoder constructor, which requires some properties
        #  that AbstractOpus sets up
        OpusEncoder.__init__(self, self.sampling_rate, self.channels)

    def __str__(self):
        return u"{pid:5}|{guild_id}|{channel_id}|{user_id}|{artist} - {title} / {duration} sec / {filesize_mb} Mb".format(**self.source.about)#.encode('utf8','ignore')#self.source.about.get("pid",None),self.source.about.get("guild_id",None),self.source.about.get("channel_id",None),self.source.about.get("user_id",None),self.source.about.get("artist",None),self.source.about.get("title",None),self.source.about.get("duration",None),self.source.about.get("filesize_mb",None))

    def __unicode__(self):
        return u"{pid:5}|{guild_id}|{channel_id}|{user_id}|{artist} - {title} / {duration} sec / {filesize_mb} Mb".format(**self.source.about)

    def check_error(self):
        try:
                have_error = self.source.process.stderr.read()
                if have_error:
                        self.source.error_embed.description = have_error
                        self.source.error_embed.add_field(name = u'Last played time:', value = u'{}'.format(sectohum(seconds=int(self.source.played))),inline=True)
                        self.source.error = have_error
        except Exception as error:
                print error
                pass

    def next_frame(self):
        if not self.source.process:
                self.source.process = subprocess.Popen(self.source.cmd_args,bufsize = 81920, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.source.about["pid"] =  self.source.process.pid
                self.source.proc_working = True
                self.source.embed.add_field(name = u'Start Playing:', value = strftime("%H:%M:%S", localtime(time())),inline=True)

        raw = self.source.process.stdout.read(int(self.frame_size))
	if len(raw) < self.frame_size:
		self.check_error()
		self.source.killed()
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
