FROM alpine

RUN apk add python3 \
    && python3 -m ensurepip \
    && pip3 install -U pip setuptools wheel

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

WORKDIR /app
COPY run.sh *.py /app/

EXPOSE 8080
CMD /app/run.sh
