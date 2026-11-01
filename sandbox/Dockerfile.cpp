FROM gcc:13
WORKDIR /app
COPY ./backend/codejudge/worker/runner/runner.py /runner/runner.py
RUN mkdir -p /code /data /out /runner && chmod -R 755 /runner
CMD ["python3", "/runner/runner.py"]
