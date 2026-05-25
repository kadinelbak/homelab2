import io from 'socket.io-client'

const URL = window.location.origin

const Socket = io(URL)

export default Socket
