@echo off
setlocal
rem Sobe o conector do Coletum no Windows. E o par do scripts\iniciar: o Codex chama ./scripts/iniciar e,
rem no Windows, acha este .cmd. Se o uv nao estiver no PATH nem ja baixado, baixa uma vez a versao fixa
rem abaixo, confere o SHA-256 e so entao extrai em %USERPROFILE%\.coletum-mcp\uv. Sem PowerShell e sem HOME.
rem O stdout e so do protocolo MCP: toda mensagem vai para o stderr (1>&2) ou para nul.
rem Textos sem acento: o cmd le este arquivo na pagina de codigo do console.
rem Trocar a versao do uv = trocar as duas linhas abaixo (hash do .sha256 publicado na release).
set "COLETUM_UV_VERSAO=0.12.24"
set "COLETUM_UV_SHA256=7c38608c8a18ee137d748a1773053b07ec8f3a30fab49aebaa6f4e4efeceb019"
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
set "DADOS=%USERPROFILE%\.coletum-mcp"
rem No app da Store (MSIX) o Windows desvia as escritas em AppData para a pasta do pacote, e o uv
rem nao acha o Python que acabou de instalar. Python e cache do uv ficam em DADOS, fora da AppData.
set "UV_PYTHON_INSTALL_DIR=%DADOS%\python"
set "UV_CACHE_DIR=%DADOS%\cache"

where uv >nul 2>&1
if not errorlevel 1 (
  set "UVEXE=uv"
  goto rodar
)
set "UVEXE=%DADOS%\uv\uv.exe"
if exist "%UVEXE%" goto rodar

echo Coletum: baixando o uv %COLETUM_UV_VERSAO% para "%DADOS%\uv", so na primeira vez. 1>&2
set "ZIP=%TEMP%\coletum-uv-%RANDOM%%RANDOM%.zip"
curl.exe -LsSf -o "%ZIP%" "https://github.com/astral-sh/uv/releases/download/%COLETUM_UV_VERSAO%/uv-x86_64-pc-windows-msvc.zip" 1>&2
if errorlevel 1 goto falha_download
certutil -hashfile "%ZIP%" SHA256 2>&1 | findstr /i /c:"%COLETUM_UV_SHA256%" >nul 2>&1
if errorlevel 1 goto falha_hash
rem ponytail: duas subidas ao mesmo tempo na 1a vez baixam em dobro; a 2a pode falhar e a proxima sobe.
if not exist "%DADOS%\uv" mkdir "%DADOS%\uv" 1>&2
tar.exe -xf "%ZIP%" -C "%DADOS%\uv" 1>&2
del /q "%ZIP%" >nul 2>&1
if not exist "%UVEXE%" goto falha_extrair

:rodar
"%UVEXE%" run --frozen --quiet --project "%RAIZ%" python "%RAIZ%\server\server.py"
exit /b %errorlevel%

:falha_download
del /q "%ZIP%" >nul 2>&1
echo Coletum: nao consegui baixar o uv. Confira a internet ou o proxy e abra o ChatGPT de novo. 1>&2
exit /b 1

:falha_hash
del /q "%ZIP%" >nul 2>&1
echo Coletum: o uv baixado nao confere com o SHA-256 esperado. Nada foi instalado nem executado. 1>&2
exit /b 1

:falha_extrair
echo Coletum: nao consegui extrair o uv em "%DADOS%\uv". 1>&2
exit /b 1
