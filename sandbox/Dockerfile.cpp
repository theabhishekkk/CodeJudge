FROM gcc:13
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY ./backend/codejudge/worker/runner/runner.py /runner/runner.py
RUN mkdir -p /code /data /out /runner && chmod -R 755 /runner
CMD ["python3", "/runner/runner.py"]
