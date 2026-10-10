# The service image. Two things are deliberate here.
#
# Poppler is installed at the version the corpus text was extracted with, the same
# pin the test workflow uses, because the extractor is part of the pipeline: see
# extractor_version in corpus/manifest.json.
#
# The index is built during the image build, not at boot. It is derived from the
# frozen corpus with a pinned model, so building it twice gives the same bytes;
# doing it here means the pod becomes ready in seconds rather than minutes, and
# that no container ever needs the network to answer.

FROM python:3.12-slim-trixie AS build

RUN apt-get update \
 && apt-get install -y --no-install-recommends 'poppler-utils=25.03.0-*' \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml README.md ./
COPY eclusa ./eclusa
RUN pip install --no-cache-dir .

COPY corpus ./corpus
COPY prompts ./prompts
# The embedding model is fetched once here, verified by hash, and carried forward.
ENV HF_HUB_CACHE=/opt/models HF_HUB_DISABLE_TELEMETRY=1
RUN python -m eclusa.index build --out /opt/index

FROM python:3.12-slim-trixie AS runtime

# pdftotext is not needed to serve: the corpus text is committed and the index is built.
# The collector is the only thing that extracts, and it does not run in this image.
RUN useradd --system --uid 10001 --home /app eclusa
WORKDIR /app

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /opt/index /opt/index
COPY --from=build /opt/models /opt/models
COPY corpus ./corpus
COPY prompts ./prompts
COPY eval/generation/recordings.jsonl ./recordings.jsonl

ENV ECLUSA_CORPUS=/app/corpus \
    ECLUSA_INDEX=/opt/index \
    ECLUSA_CASSETTE=/app/recordings.jsonl \
    ECLUSA_AUDIT=/var/lib/eclusa/trail.jsonl \
    HF_HUB_CACHE=/opt/models \
    HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /var/lib/eclusa && chown eclusa:eclusa /var/lib/eclusa
USER 10001
EXPOSE 8000

# The service answers from recordings unless ECLUSA_LIVE=1 and a key are both set,
# so this container needs no network and no secret to be useful.
CMD ["uvicorn", "eclusa.service.app:app", "--host", "0.0.0.0", "--port", "8000"]
