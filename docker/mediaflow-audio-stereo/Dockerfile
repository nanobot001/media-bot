FROM mhdzumair/mediaflow-proxy:v2.4.9@sha256:3b8e30f246ced9c61b4f9e4cd4aeb99b860b23b15f85a3c6d5c711dccbf1ce97

COPY patch_mediaflow_audio.py /tmp/patch_mediaflow_audio.py
RUN python /tmp/patch_mediaflow_audio.py
