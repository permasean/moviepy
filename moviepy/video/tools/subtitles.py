"""Experimental module for subtitles support."""

import re

import numpy as np

from moviepy.decorators import convert_path_to_string
from moviepy.tools import convert_to_seconds
from moviepy.video.VideoClip import TextClip, VideoClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip


class SubtitlesClip(VideoClip):
    """A Clip that serves as "subtitle track" in videos.

    One particularity of this class is that the images of the
    subtitle texts are not generated beforehand, but only if
    needed.

    Parameters
    ----------

    subtitles
      Either the name of a file as a string or path-like object, or a list

    encoding
      Optional, specifies srt file encoding.
      Any standard Python encoding is allowed (listed at
      https://docs.python.org/3.8/library/codecs.html#standard-encodings)

    Examples
    --------

    >>> from moviepy.video.tools.subtitles import SubtitlesClip
    >>> from moviepy.video.io.VideoFileClip import VideoFileClip
    >>> generator = lambda text: TextClip(text, font='Georgia-Regular',
    ...                                   font_size=24, color='white')
    >>> sub = SubtitlesClip("subtitles.srt", generator)
    >>> sub = SubtitlesClip("subtitles.srt", generator, encoding='utf-8')
    >>> myvideo = VideoFileClip("myvideo.avi")
    >>> final = CompositeVideoClip([clip, subtitles])
    >>> final.write_videofile("final.mp4", fps=myvideo.fps)

    """
    def __init__(self, subtitles, make_textclip=None, encoding=None, ssrt=False):
        VideoClip.__init__(self, has_constant_size=False)

        # text: word-by-word styling []
        self.sub_styles = {}

        if not isinstance(subtitles, list):
            # `subtitles` is a string or path-like object
            if ssrt:
                [subtitles, sub_styles] = ssrt_to_subtitles(subtitles, encoding=encoding)
                self.sub_styles = sub_styles
            else:
                subtitles = file_to_subtitles(subtitles, encoding=encoding)

        # subtitles = [(map(convert_to_seconds, times), text)
        #              for times, text in subtitles]
        self.subtitles = subtitles
        self.textclips = dict()

        if make_textclip is None:
            if ssrt:
                def make_textclip(sub_style):
                    if isinstance(sub_style, str):
                        return TextClip(
                            sub_style,
                            font="Georgia-Bold",
                            fontsize=24,
                            color="white",
                            stroke_color="black",
                            stroke_width=0.5,
                            # bg_color
                            # kerning
                        ) 
                    
                    text_clips = []
                    current_x_offset = 0
                    for i, word in enumerate(sub_style):
                        if "stroke_color" in word:
                            stroke_color = word["stroke_color"]
                        else:
                            stroke_color = None
                        
                        if "stroke_width" in word:
                            stroke_width = word["stroke_width"]
                        else:
                            stroke_width = 1

                        if "bg_color" in word:
                            bg_color = word["bg_color"]
                        else:
                            bg_color = "transparent"
                            
                        text_clip = TextClip(
                            word["text"],
                            font=word["font"],
                            fontsize=word["size"],
                            color=word["color"],
                            stroke_color=stroke_color,
                            stroke_width=stroke_width,
                            bg_color=bg_color,
                        )

                        # text_clip.set_position((0, 0))

                        if i == 0:
                            text_clips.append(text_clip.set_position((0, "top")))
                        else:
                            current_x_offset += text_clips[i-1].w
                            text_clips.append(text_clip.set_position((current_x_offset, "top")))

                        if i == len(sub_style)-1:
                            current_x_offset += text_clip.w

                    return CompositeVideoClip(text_clips, size=(current_x_offset, text_clips[0].h))
            else:
                def make_textclip(txt):
                    return TextClip(
                        txt,
                        font="Georgia-Bold",
                        fontsize=24,
                        color="white",
                        stroke_color="black",
                        stroke_width=0.5,
                    )

        self.make_textclip = make_textclip
        self.start = 0
        self.duration = max([tb for ((ta, tb), txt) in self.subtitles])
        self.end = self.duration

        def add_textclip_if_none(t):
            """Will generate a textclip if it hasn't been generated asked
            to generate it yet. If there is no subtitle to show at t, return
            false.
            """
            sub = [
                ((text_start, text_end), text)
                for ((text_start, text_end), text) in self.textclips.keys()
                if (text_start <= t < text_end)
            ]
            if not sub:
                sub = [
                    ((text_start, text_end), text)
                    for ((text_start, text_end), text) in self.subtitles
                    if (text_start <= t < text_end)
                ]
                if not sub:
                    return False
            sub = sub[0]
            if sub not in self.textclips.keys():
                if ssrt:
                    if sub in sub_styles:
                        sub_style = sub_styles[sub]
                        self.textclips[sub] = self.make_textclip(sub_style)
                    else:
                        raise Exception("Unexpected behavior exception: key does not exist in sub_styles")
                else:
                    self.textclips[sub] = self.make_textclip(sub[1])

            return sub

        def make_frame(t):
            sub = add_textclip_if_none(t)
            return self.textclips[sub].get_frame(t) if sub else np.array([[[0, 0, 0]]])

        def make_mask_frame(t):
            sub = add_textclip_if_none(t)
            return self.textclips[sub].mask.get_frame(t) if sub else np.array([[0]])

        self.make_frame = make_frame
        hasmask = bool(self.make_textclip("T").mask)
        self.mask = VideoClip(make_mask_frame, is_mask=True) if hasmask else None

    def in_subclip(self, start_time=None, end_time=None):
        """Returns a sequence of [(t1,t2), text] covering all the given subclip
        from start_time to end_time. The first and last times will be cropped so as
        to be exactly start_time and end_time if possible.
        """

        def is_in_subclip(t1, t2):
            try:
                return (start_time <= t1 < end_time) or (start_time < t2 <= end_time)
            except Exception:
                return False

        def try_cropping(t1, t2):
            try:
                return max(t1, start_time), min(t2, end_time)
            except Exception:
                return t1, t2

        return [
            (try_cropping(t1, t2), txt)
            for ((t1, t2), txt) in self.subtitles
            if is_in_subclip(t1, t2)
        ]

    def __iter__(self):
        return iter(self.subtitles)

    def __getitem__(self, k):
        return self.subtitles[k]

    def __str__(self):
        def to_srt(sub_element):
            (start_time, end_time), text = sub_element
            formatted_start_time = convert_to_seconds(start_time)
            formatted_end_time = convert_to_seconds(end_time)
            return "%s - %s\n%s" % (formatted_start_time, formatted_end_time, text)

        return "\n\n".join(to_srt(sub) for sub in self.subtitles)

    def match_expr(self, expr):
        """Matches a regular expression against the subtitles of the clip."""
        return SubtitlesClip(
            [sub for sub in self.subtitles if re.findall(expr, sub[1]) != []]
        )

    def write_srt(self, filename):
        """Writes an ``.srt`` file with the content of the clip."""
        with open(filename, "w+") as file:
            file.write(str(self))


@convert_path_to_string("filename")
def file_to_subtitles(filename, encoding=None):
    """Converts a srt file into subtitles.

    The returned list is of the form ``[((start_time,end_time),'some text'),...]``
    and can be fed to SubtitlesClip.

    Only works for '.srt' format for the moment.
    """
    times_texts = []
    current_times = None
    current_text = ""

    with open(filename, "r", encoding=encoding) as f:
        for line in f:
            times = re.findall("([0-9]*:[0-9]*:[0-9]*,[0-9]*)", line)
            if times:
                current_times = [convert_to_seconds(t) for t in times]
            elif line.strip() == "":
                times_texts.append((current_times, current_text.strip("\n")))
                current_times, current_text = None, ""
            elif current_times:
                current_text += line

    return times_texts

@convert_path_to_string("filename")
def ssrt_to_subtitles(filename, encoding=None):
    """Converts a sSRT (styledSRT) file into subtitles.

    The returned list is of the form ``[((ta,tb),'some text'),...]``
    and a mapping of text : word-by-word styling
    and can be fed to SubtitlesClip.

    Only works for '.json' format for the moment.
    """
    import json

    with open(filename, "r", encoding=encoding) as f:
        data = json.load(f)
    
    subtitles = []
    ss = {}

    for line in data:
        start_ts = line["startTimestamp"]/1000
        end_ts = line["endTimestamp"]/1000
    
        line_text = ""
        for j, word in enumerate(line["words"]):
            if j < len(line["words"]):
                line_text += word["text"] + " "
        
        sub = ((start_ts, end_ts), line_text)
        subtitles.append(sub)

        for j, word in enumerate(line["words"]):
            if j < len(line["words"]):
                word["text"] += " "

            if sub not in ss:
                ss[sub] = [word]
            elif sub in ss:
                sub_ws = ss[sub]
                sub_ws.append(word)
                ss[sub] = sub_ws

    return [subtitles, ss]