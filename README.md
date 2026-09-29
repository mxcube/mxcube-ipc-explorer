# mxcube-ipc-explorer

A console UI for using (exploring) the mxcubecore IPC system `mxcubecore.ipc` interactively.

## Install

This depends on `mxcube-ipc-client`

```console
pip install -e ../mxcube-ipc-client
pip install -e .
```

It doesn't need `mxcubecore` itself - only a running `IPCServer` to
connect to.

## Run

```console
mxcube-ipc-explorer --token change-me
mxcube-ipc-explorer --token change-me --transport nanomq
mxcube-ipc-explorer --token change-me --log-file /tmp/explorer.log
```

Or without installing the console script:

```console
python -m mxcube_ipc_explorer --token change-me
```
