""" Experimental module for subtitles support. """

import re

import numpy as np

from moviepy.decorators import convert_path_to_string
from moviepy.tools import cvsecs
from moviepy.video.VideoClip import TextClip, VideoClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip


class SubtitlesClip(VideoClip):
    """A Clip that serves as "subtitle track" in videos.

    One particularity of this class is that the images of the
    subtitle texts are not generated beforehand, but only if
    needed.

    Parameters
    ==========

    subtitles
      Either the name of a file as a string or path-like object, or a list

    encoding
      Optional, specifies srt file encoding.
      Any standard Python encoding is allowed (listed at https://docs.python.org/3.8/library/codecs.html#standard-encodings)

    Examples
    =========

    >>> from moviepy.video.tools.subtitles import SubtitlesClip
    >>> from moviepy.video.io.VideoFileClip import VideoFileClip
    >>> generator = lambda txt: TextClip(txt, font='Georgia-Regular', fontsize=24, color='white')
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

        # subtitles = [(map(cvsecs, tt),txt) for tt, txt in subtitles]
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
                        ) 
                    
                    text_clips = []
                    for i, word in enumerate(sub_style):
                        text_clip = TextClip(
                            word["text"],
                            font=word["font"],
                            fontsize=word["size"],
                            color=word["color"],
                            stroke_color="black",
                            stroke_width=0.5,
                        )
                        text_clips.append(text_clip)

                    return CompositeVideoClip(text_clips)
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
            false."""
            sub = [
                ((ta, tb), txt)
                for ((ta, tb), txt) in self.textclips.keys()
                if (ta <= t < tb)
            ]
            if not sub:
                sub = [
                    ((ta, tb), txt)
                    for ((ta, tb), txt) in self.subtitles
                    if (ta <= t < tb)
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
        self.mask = VideoClip(make_mask_frame, ismask=True) if hasmask else None

    def in_subclip(self, t_start=None, t_end=None):
        """Returns a sequence of [(t1,t2), txt] covering all the given subclip
        from t_start to t_end. The first and last times will be cropped so as
        to be exactly t_start and t_end if possible."""

        def is_in_subclip(t1, t2):
            try:
                return (t_start <= t1 < t_end) or (t_start < t2 <= t_end)
            except Exception:
                return False

        def try_cropping(t1, t2):
            try:
                return (max(t1, t_start), min(t2, t_end))
            except Exception:
                return (t1, t2)

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
            (ta, tb), txt = sub_element
            fta = cvsecs(ta)
            ftb = cvsecs(tb)
            return "%s - %s\n%s" % (fta, ftb, txt)

        return "\n\n".join(to_srt(s) for s in self.subtitles)

    def match_expr(self, expr):

        return SubtitlesClip(
            [e for e in self.subtitles if re.findall(expr, e[1]) != []]
        )

    def write_srt(self, filename):
        with open(filename, "w+") as f:
            f.write(str(self))


@convert_path_to_string("filename")
def file_to_subtitles(filename, encoding=None):
    """Converts a srt file into subtitles.

    The returned list is of the form ``[((ta,tb),'some text'),...]``
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
                current_times = [cvsecs(t) for t in times]
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