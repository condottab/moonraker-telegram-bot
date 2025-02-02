# Please open PR only in `development` branch

# Setup environment
## Active virtualenv
This is the default location.
```shell
source ~/moonraker-telegram-bot-env/bin/activate
```
## Install dependencies
```shell
pip install -r scripts/requirements.dev.txt
```
## Install pre-commit hook
```shell
pre-commit install
```

You can also run pre-commit manually on all files:
Before commiting changes you should also run pre-commit and tests manually on all files:
```shell
pre-commit run --all-files  --show-diff-on-failure --color=always
pytest -v
```

Run bot localy:

create dev config file `telegram_dev.conf ` for example in bot folder
```shell
cd ~/moonraker-telegram-bot
~/moonraker-telegram-bot-env/bin/python3 ~/moonraker-telegram-bot/bot/main.py -c ~/moonraker-telegram-bot/telegram_dev.conf
```

Test changes using docker and arm64 arc( docker buildx or docker desktop required). New container with the bot will be created and started.
```shell
pre-commit run --all-files
docker compose -f .\docker-compose-dev.yml up --build -d
```
you mast create bot config file under `./docker_data/config` or copy created earlier telegram_dev.conf to container config folder and rename in to `telegram.conf`
dev container contains preinstalled `memray` and `memory-profiler` for easy memory problem retrieval

Test building docker images (buildx required):
```shell
docker buildx build --platform linux/arm64 -t test -f Dockerfile-mjpeg .
docker buildx build --platform linux/arm64 -t test -f Dockerfile .
```
