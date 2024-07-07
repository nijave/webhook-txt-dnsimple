FROM python:3-alpine

ARG PIP_DISABLE_PIP_VERSION_CHECK=1
ARG PIP_NO_CACHE_DIR=1

RUN apk add python3 \
    && python3 -m ensurepip \
    && pip3 install -U pip setuptools wheel

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

WORKDIR /app
COPY run.sh *.py /app/

EXPOSE 8080
CMD /app/run.sh
