# Postgres-testing

An attempt to document my testing with Postgres in Docker, and interfacting it with Python

## Index

- [Initial Setup](#Initial-Setup)
- [Docker Setup](#Docker-Setup)

## Initial Setup

Things to make sure you have setup before starting the tutorial.

### Docker setup w/ WSL

I already had [Docker Desktop](https://www.docker.com/products/docker-desktop) installed at the time of writing. I did have to enable the built-in WSL Integration by right-clicking the Docker icon in the taskbar, click settings, then enable `Resources > WSL Integration > Ubuntu`.

Be sure Docker is installed in WSL by running `docker --version`. If not, install it with `apt install docker.io`.

Now you should be ready to go!

### pgAdmin 4

I downloaded and installed [pgAdmin 4](https://www.pgadmin.org/download/) for Windows. This can be run in a Docker container, but I figured this would be easier.

After installing, give pgAdmin a launch to set a master password. This can be anything, but be sure you don't fat-finger it. There's not a 2nd password prompt.

pgAdmin should be setup for you now.

## Docker Setup

Instructions for how to setup and connect to a postgres instance with Docker.

### Quick Links

[Postgres - Docker Hub](https://hub.docker.com/_/postgres)
[Postgres config file](./my-postgres.conf)

### Important notes

The location wehre Posatgres stores all its data is, by default, `/var/lib/postgresql/data`. This can be changed by defining **PGDATA**.

### Building the container

The following command will create the _postgres_ container with the following params:

- Run the container in the background
  - `-d`
- Expose port _5432_ as-is
  - `-p 5432:5432/tcp`
- Name the container instance _postgres_
  - `--name postgres`
- Set the _postgres_ admin user's password to `postgres`
  - `-e POSTGRES_PASSWORD=postgres`

`docker run -d -p 5432:5432/tcp --name postgres -e POSTGRES_PASSWORD=postgres postgres`

After executing the above command, you should be able to connect to the instance through pgAdmin by connecting to `127.0.0.1`, using `postgres` as the username and password.
