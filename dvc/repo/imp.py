def imp(
    self,
    url,
    path,
    out=None,
    rev=None,
    config=None,
    remote=None,
    remote_config=None,
    **kwargs,
):
    erepo = {"url": url}
    if rev is not None:
        erepo["rev"] = rev

    if config is not None:
        erepo["config"] = config

    if remote is not None and remote_config is not None:
        conf = erepo.get("config") or {}
        remotes = conf.get("remote") or {}
        remote_conf = remotes.get(remote) or {}
        remote_conf.update(remote_config)
        remotes[remote] = remote_conf
        conf["remote"] = remotes
        erepo["config"] = conf
    elif remote is not None:
        erepo["remote"] = remote
    elif remote_config is not None:
        erepo["remote"] = remote_config

    return self.imp_url(path, out=out, erepo=erepo, frozen=True, **kwargs)
