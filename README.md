# Stoq-server

## Development setup

...

## CI

### Refreshing the testing container

Rebuild a container `candidade` with proposed changes to the `Dockerfile`:

    docker build -t stoq:candidate .

Push the `candidate` container to dockerhub (ensure you are logged in):

    docker push cprov/stoq:candidate

Then, point `.gitlab-ci.yml` to the `candidate` container:

    image: cprov/stoq:stable

and update your branch.

Once it passes CI, promote the `candidate` contained to `stable`:

    docker tag <hash> cprov/stoq:stable
    docker push cprov/stoq:stable

And restore `.gitlab-ci.yml` in your branch to the `stable` container.
