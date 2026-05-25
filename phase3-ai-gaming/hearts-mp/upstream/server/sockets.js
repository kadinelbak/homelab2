const cardsLib = require('./cards')
const Deck = cardsLib.Deck
const CardSuit = cardsLib.CardSuit
const evaluateTrick = cardsLib.evaluateTrick

const sleep = ms => {
	return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * User schema
 *
 * 'id': {
 *    name: String,
 *    room: String,
 *    voted: Boolean,
 *    hand: [Card],
 *    points: Number
 * }
 */
var users = {}

/**
 * A dictionary of pending setTimeout handlers for disconnecting users
 */
var disconnects = {}

/**
 * Room schema
 *
 * 'id': {
 *    members: [id],
 *    open: Boolean,
 *    moveCount: Number, (-1 for haven't started)
 *    heartsBroken: Boolean,
 * 		turn: -1,
 * 		trick: [Card]
 * }
 */
var rooms = {}

const hat = length => {
	var text = ''
	var possible = 'abcdef0123456789'

	for (var i = 0; i < length; i++)
		text += possible.charAt(Math.floor(Math.random() * possible.length))

	return text
}

module.exports = server => {
	const io = require('socket.io')(server, {
		origins: '*:*'
	})

	const updatePlayers = roomId => {
		io.to(roomId).emit(
			'updatePlayers',
			rooms[roomId].members.map(m => {
				var u = { ...users[m] }
				u.id = m
				return u
			})
		)
	}

	io.on('connection', socket => {
		// autoassign id
		var id = hat(8)
		while (Object.keys(users).includes(id)) {
			id = hat(8)
		}

		// send id to client
		socket.emit('id', id)
		socket.join(id)

		// handle setName from client
		socket.on('setName', name => {
			if (users[id]) return

			users[id] = {
				name,
				room: null,
				voted: false,
				hand: [],
				points: 0
			}
		})

		socket.on('createRoom', () => {
			if (users[id].room) return

			// autoassign roomId
			var roomId = hat(6)
			while (Object.keys(rooms).includes(roomId)) {
				roomId = hat(6)
			}

			rooms[roomId] = {
				members: [id],
				open: true,
				moveCount: -1,
				heartsBroken: false,
				turn: 0,
				trick: []
			}
			users[id].room = roomId

			socket.emit('roomId', roomId)
			socket.join(roomId)
		})

		socket.on('joinRoom', roomId => {
			if (
				users[id].room ||
				!rooms[roomId] ||
				rooms[roomId].members.length >= 4 ||
				!rooms[roomId].open
			)
				return

			rooms[roomId].members.push(id)
			socket.join(roomId)
			users[id].room = roomId

			// push new players to entire group
			updatePlayers(roomId)
		})

		socket.on('leaveRoom', () => {
			if (!users[id] || !users[id].room) return

			const roomId = users[id].room
			const room = rooms[roomId]
			socket.leave(roomId)

			if (room.members.length <= 1) {
				delete rooms[roomId]
				users[id].room = null
			} else {
				room.members.splice(room.members.indexOf(id), 1)
				users[id].room = null
				updatePlayers(roomId)
			}
		})

		socket.on('voteStart', () => {
			if (!users[id].room) return

			users[id].voted = true
			updatePlayers(users[id].room)

			// check if game is ready to start
			const roomId = users[id].room
			const room = rooms[roomId]
			if (room.members.length < 4) return
			for (var i = 0; i < room.members.length; i++) {
				var member = users[room.members[i]]
				if (!member.voted) return
			}

			// game is ready to start
			// close the room
			room.open = false
			room.moveCount = 0
			room.heartsBroken = false
			room.turn = -1
			room.trick = []

			// deal the cards
			const hands = new Deck().deal()

			room.members.forEach((m, i) => {
				users[m].hand = hands[i].cards
				users[m].points = 0

				io.to(m).emit('startGame', hands[i])

				// check to see if cards contain the 2 of clubs; player with 2 of clubs starts
				if (
					users[m].hand.filter(m => m.number === 2 && m.suit === CardSuit.CLUBS)
						.length > 0
				) {
					room.turn = i
					io.to(m).emit('yourTurn')
				}
			})
		})

		socket.on('disconnect', () => {
			const handler = setTimeout(() => {
				if (!users[id] || !users[id].room) return

				const roomId = users[id].room
				const room = rooms[roomId]
				socket.leave(roomId)
				if (room.members.length <= 1) {
					delete rooms[roomId]
				} else {
					room.members.splice(room.members.indexOf(id), 1)
					updatePlayers(roomId)
				}
				delete users[id]
			}, 3000)

			disconnects[id] = handler
		})

		// GAME MECHANICS
		socket.on('playCard', async card => {
			if (!users[id]) return
			const roomId = users[id].room
			const room = rooms[roomId]

			// return if game hasn't started
			if (!room.moveCount < 0) return

			// check user's turn
			if (room.turn !== room.members.indexOf(id)) return

			var hand = users[id].hand

			// check user actually has the card
			let cardIndex = hand.length - 1
			for (; cardIndex >= 0; cardIndex--) {
				const thisCard = hand[cardIndex]
				if (thisCard.number === card.number && thisCard.suit === card.suit)
					break
			}
			if (cardIndex < 0) return

			// only allow 2 of clubs on first move
			if (
				room.moveCount === 0 &&
				(card.number !== 2 || card.suit !== CardSuit.CLUBS)
			)
				return

			// only allow same suit (if this is not first card of trick, and if the player has cards of that suit)
			if (room.trick.length > 0) {
				const firstCard = room.trick[0]

				if (firstCard.suit !== card.suit) {
					// return if player has more cards of this suit
					if (hand.filter(c => c.suit === firstCard.suit).length > 0) return
				}
			} else {
				// if first card of trick, check if is hearts if hearts havent been broken
				if (card.suit === CardSuit.HEARTS && !room.heartsBroken) return
			}

			// remove card from player and add to trick
			room.trick.push(hand.splice(cardIndex, 1)[0])

			// emit to sockets
			io.to(roomId).emit('cardPlayed', card, id)
			socket.emit('turnEnd')

			// check if hearts break
			if (!room.heartsBroken && card.suit === CardSuit.HEARTS)
				room.heartsBroken = true

			// increment move
			room.moveCount++

			// if this is last card of trick, clear the trick and add up points
			if (room.trick.length === 4) {
				// evaluate the trick
				const result = evaluateTrick(room.trick)
				let taker = result.taker + room.turn + 1
				if (taker > 3) taker -= 4
				users[room.members[taker]].points += result.points
				io.to(roomId).emit('highlightCard', taker)

				await sleep(2000)

				io.to(roomId).emit('pointsChanged', taker, result.points)

				// clear the trick
				room.trick.splice(0, 4)
				io.to(roomId).emit('clearTrick')

				// check if game is over
				console.log('move ' + room.moveCount)
				if (room.moveCount >= 52) {
					console.log('sent gameover')
					room.members.forEach(mId => (users[mId].voted = false))
					io.to(roomId, 'gameOver')
					return
				}

				// make the taker start the next trick
				room.turn = taker
				io.to(roomId).emit('changeTurn', taker)
				// io.to(room.members[taker]).emit('yourTurn')
			} else {
				room.turn++
				if (room.turn > 3) room.turn = 0
				io.to(roomId).emit('changeTurn', room.turn)
				// io.to(room.members[room.turn]).emit('yourTurn')
			}
		})
	})
}
