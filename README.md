# Stoq-server

## Development setup

...

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
