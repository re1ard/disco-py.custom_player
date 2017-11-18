# disco-py.custom_player
ну кароче говоря 4 файла 

1.(magnitola.py) - это плагин для бота, который используется в ретарда для дискорда

this plugin for bot

2.(player.py) - это модифицированная версия (https://github.com/b1naryth1ef/disco/blob/master/disco/voice/player.py) где изменина одна строчка, в функции skip

moding original file

3.(player_codecs.py) - это модифицированная версия (https://github.com/b1naryth1ef/disco/blob/master/disco/voice/playable.py) где собственная все придуманные костыли и убрано все не нужное

moding original file, add memory leak fix

4.(playlist_support.py) - это для поддержки плейлистов из vk.com

support playlists from vk.com

костыли:
самый главный костыль, исправлена утечка памяти(memory leak) из-за которой мог упасть бот, ибо ну очень уж много памяти оставляли треки которые уже проигрались
при добавление ссылки с музыкой в очередь,нагружался цопе,сильно.. теперь он лишь думает когда читается сам пайп

