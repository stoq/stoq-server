# Stoq-server

## Development setup

First you have to have [Poetry] installed and running on your machine.

This project use packages from [Gitlab PyPI]. You'll have to generate a
gitlab [personal access token] with `read_api` persmission.

Then configure the gitlab repository within poetry:

```
$ poetry config repositories.gitlab https://gitlab.com/api/v4/projects/13882298/packages/pypi
```

And now setup the authentication replacing the `<personal-access-token>`
with the token generated previously:

```
$ poetry config http-basic.gitlab __token__ <personal-access-token>
```

Now you're ready to download all the packages and to install everything with:
```
$ poetry install
```

Then check everything has been installed correctly run the tests:
```
$ make test
```

Then run stoqserver:
```
$ make flask
```

If everything executed without errors you're good to go.


## CI


### Running CI locally

Install `gitlab-runner`

    sudo curl -L --output /usr/local/bin/gitlab-runner https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-amd64
    sudo chmod +x /usr/local/bin/gitlab-runner

Install the `docker` snap

    sudo snap install docker
    docker.help
    # Follow the instructions for classic systems
    sudo snap restart docker

Run the CI for the local project

    gitlab-runner exec docker test


### Refreshing the testing container

Rebuild a container `candidade` with proposed changes to the `Dockerfile`:

    docker build -t stoq:candidate -f utils/Dockerfile.stoq .

Push the `candidate` container to dockerhub (ensure you are logged in):

    docker push cprov/stoq:candidate

Then, point `.gitlab-ci.yml` to the `candidate` container:

    image: cprov/stoq:stable

and update your branch.

Once it passes CI, promote the `candidate` contained to `stable`:

    docker tag <hash> cprov/stoq:stable
    docker push cprov/stoq:stable

And restore `.gitlab-ci.yml` in your branch to the `stable` container.


[personal access token]: https://gitlab.com/-/profile/personal_access_tokens
[Poetry]: https://github.com/python-poetry/poetry/
[Gitlab PyPI]: https://docs.gitlab.com/ee/user/packages/pypi_repository/index.html
