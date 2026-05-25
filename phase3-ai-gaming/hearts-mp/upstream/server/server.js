'use strict'

const path = require('path')
const express = require('express')
const app = express()
const port = process.env.PORT

if (!port) {
  throw new Error('Specify PORT environment variable')
}

app.use(function(req, res, next) {
	res.header('Access-Control-Allow-Origin', '*')
	res.header('Access-Control-Allow-Headers', 'X-Requested-With')
	res.header('Access-Control-Allow-Headers', 'Content-Type')
	res.header('Access-Control-Allow-Methods', 'PUT, GET, POST, DELETE, OPTIONS')
	next()
})

const publicDir = path.join(__dirname, 'public')
app.use(express.static(publicDir))

app.get('/health', (req, res) => {
	res.json({ status: 'ok', game: 'hearts' })
})

const server = require('http').Server(app)

// attach socket.io api
require('./sockets')(server)

app.get('*', (req, res) => {
	res.sendFile(path.join(publicDir, 'index.html'))
})

server.listen(port, () => {
	console.log('Hearts API is live on port ' + port + '\n')
})
