const io = require('socket.io-client')
const socket1 = io('http://localhost:3000')
const socket2 = io('http://localhost:3000')

var socket1Id
var socket2Id
var roomId

socket1.on('id', id => {
	socket1Id = id
})

socket2.on('id', id => {
	socket2Id = id
})

socket1.emit('setName', 'terrance')
socket2.emit('setName', 'owen')

socket1.emit('createRoom')

socket1.on('roomId', roomId => {
	roomId = roomId

	socket2.emit('joinRoom', roomId)
})
