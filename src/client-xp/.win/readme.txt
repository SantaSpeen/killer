Папка с ресурсами для сборки под Windows.

Для сборки проекта под Windows необходимо установить следующие пакеты:

pip install auto-py-to-exe
pip install pyinstaller-versionfile

Для сборки проекта под Windows необходимо выполнить следующие команды:
create-version-file metadata.yml --outfile version.txt
auto-py-to-exe -с auto.json
