# Hearts
An online room-based card game: Hearts

# Getting Started

## Prerequisites

- Node.js: `10.3.0`
- NPM: `6.4.0`
- yarn
- pm2
- serve

## Setup

Clone this repository...
```
git clone git@github.com:darkterbear/hearts
cd hearts/
```

Install dependencies
```
scripts/setup.sh
```

The client `./src/sockets.js` contains the URL for the server. It is set to `localhost:3001` by default, and the server runs on port 3001. However, if you are hosting the server elsewhere, change the `const URL` in `./src/sockets.js` to the hostname and port of your host.

## Development
Simply run `npm start` in `client/` or `server/`.

## Production
Run `scripts/deploy.sh`. CAUTION: this resets all changes in Git-tracked files!

# Built With
- Express.js
- React
- Socket.io and Socket.io Client

# Author
- Terrance Li - _initial work_

# License
This project is licensed under the MIT License - see the LICENSE.md file for details
