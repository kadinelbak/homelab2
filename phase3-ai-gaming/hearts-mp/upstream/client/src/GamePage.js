import React, { Component } from 'react'
import Card from './Card'
import Socket from './sockets'

export default class GamePage extends Component {
	constructor(props) {
		super(props)

		const bundle = props.location.state

		const opponentStartCards = Array.from({ length: 13 }, (_, i) => (
			<Card key={i} flip={true} />
		))
		this.state = {
			cards: bundle.hand,
			id: bundle.id,
			roomId: bundle.roomId,
			players: bundle.players,
			acrossCards: opponentStartCards.slice(),
			leftCards: opponentStartCards.slice(),
			rightCards: opponentStartCards.slice(),
			highlightedCard: -1,
			myTurn: false,
			playedCards: []
		}

		Socket.on('gameOver', () => {
			// received gameover
			console.log('received gameover')
			this.props.history.push('/lobby', {
				roomId: this.state.roomId,
				id: this.state.id,
				players: this.state.players
			})
		})

		Socket.on('highlightCard', taker => {
			const playerIds = this.state.players.map(p => p.id)
			const myIndex = playerIds.indexOf(this.state.id)

			var normalizedPlayerIndex = taker + (4 - myIndex)
			if (normalizedPlayerIndex > 3) normalizedPlayerIndex -= 4

			this.setState({ highlightedCard: normalizedPlayerIndex })
		})

		Socket.on('changeTurn', taker => {
			if (this.state.players[taker].id === this.state.id) {
				this.setState({ myTurn: true, turn: -1 })
			} else {
				const playerIds = this.state.players.map(p => p.id)
				const myIndex = playerIds.indexOf(this.state.id)

				var normalizedPlayerIndex = taker + (4 - myIndex)
				if (normalizedPlayerIndex > 3) normalizedPlayerIndex -= 4

				this.setState({ turn: normalizedPlayerIndex })
			}
		})

		Socket.on('yourTurn', () => {
			this.setState({ myTurn: true })
		})

		Socket.on('turnEnd', () => {
			this.setState({ myTurn: false })
		})

		Socket.on('clearTrick', () => {
			this.setState({ playedCards: [], highlightedCard: -1 })
		})

		Socket.on('pointsChanged', (taker, points) => {
			var players = this.state.players.slice()
			players[taker].points += points
			this.setState({ players })
		})

		Socket.on('cardPlayed', (card, player) => {
			if (player === this.state.id) {
				// player is meeee
				// remove card from state.cards
				var playedCards = this.state.playedCards.slice()
				playedCards[0] = card
				this.setState({
					cards: this.state.cards
						.slice()
						.filter(c => !(c.suit === card.suit && c.number === card.number)),
					playedCards
				})
			} else {
				// player is not meeee

				const playerIds = this.state.players.map(p => p.id)
				const myIndex = playerIds.indexOf(this.state.id)
				const playerIndex = playerIds.indexOf(player)

				var normalizedPlayerIndex = playerIndex + (4 - myIndex)
				if (normalizedPlayerIndex > 3) normalizedPlayerIndex -= 4

				var playedCards = this.state.playedCards.slice()
				playedCards[normalizedPlayerIndex] = card

				switch (normalizedPlayerIndex) {
					case 1:
						this.setState({
							leftCards: this.state.leftCards
								.slice()
								.splice(0, this.state.leftCards.length - 1),
							playedCards
						})
						break
					case 2:
						this.setState({
							acrossCards: this.state.acrossCards
								.slice()
								.splice(0, this.state.acrossCards.length - 1),
							playedCards
						})
						break
					case 3:
						this.setState({
							rightCards: this.state.rightCards
								.slice()
								.splice(0, this.state.rightCards.length - 1),
							playedCards
						})
						break
				}
			}
		})
	}

	onCardSelect(card) {
		Socket.emit('playCard', card)
	}

	render() {
		const cards = this.state.cards
			? this.state.cards.map(c => {
					return (
						<Card
							key={c.suit + ' ' + c.number}
							suit={c.suit}
							number={c.number}
							onClick={() => this.onCardSelect(c)}
						/>
					)
			  })
			: null

		const myCard = this.state.playedCards[0]
		const leftCard = this.state.playedCards[1]
		const acrossCard = this.state.playedCards[2]
		const rightCard = this.state.playedCards[3]

		const cardToFilename = card => {
			const suit = (suit => {
				switch (suit) {
					case 0:
						return 'h'
					case 1:
						return 's'
					case 2:
						return 'c'
					case 3:
						return 'd'
				}
			})(card.suit)

			let number = card.number
			if (number < 10) number = '0' + number
			else number = '' + number

			return suit + number
		}

		const myIndex = this.state.players.map(p => p.id).indexOf(this.state.id)

		return (
			<div className="wrapper game">
				<div className="myCards">
					<h2 className="message">
						{this.state.players[
							this.state.players.map(p => p.id).indexOf(this.state.id)
						].points +
							' points' +
							(this.state.myTurn ? '; your turn!' : '')}
					</h2>
					{cards}
				</div>
				<div className="leftCards">
					<h2
						className={
							'sideScoreIndicator' + (this.state.turn === 1 ? ' turn' : '')
						}>
						{this.state.players[myIndex + 1 > 3 ? 0 : myIndex + 1].name + ': '}
						{this.state.players[myIndex + 1 > 3 ? 0 : myIndex + 1].points}
					</h2>
					{this.state.leftCards}
				</div>
				<div className="rightCards">
					<h2
						className={
							'sideScoreIndicator' + (this.state.turn === 3 ? ' turn' : '')
						}>
						{this.state.players[myIndex + 3 > 3 ? myIndex + 3 - 4 : myIndex + 3]
							.name + ': '}
						{
							this.state.players[
								myIndex + 3 > 3 ? myIndex + 3 - 4 : myIndex + 3
							].points
						}
					</h2>
					{this.state.rightCards}
				</div>
				<div className="acrossCards">
					<h2
						className={
							'topScoreIndicator' + (this.state.turn === 2 ? ' turn' : '')
						}>
						{this.state.players[myIndex + 2 > 3 ? myIndex + 2 - 4 : myIndex + 2]
							.name + ': '}
						{
							this.state.players[
								myIndex + 2 > 3 ? myIndex + 2 - 4 : myIndex + 2
							].points
						}
					</h2>
					{this.state.acrossCards}
				</div>
				<div className="playedCards">
					<img
						className={
							'leftCard' +
							(this.state.highlightedCard === 1 ? ' highlight' : '')
						}
						src={
							leftCard
								? '/assets/cards/' + cardToFilename(leftCard) + '.svg'
								: '/assets/cards/blank.svg'
						}
					/>
					<div className="playedCardsVert">
						<img
							className={
								'acrossCard' +
								(this.state.highlightedCard === 2 ? ' highlight' : '')
							}
							src={
								acrossCard
									? '/assets/cards/' + cardToFilename(acrossCard) + '.svg'
									: '/assets/cards/blank.svg'
							}
						/>
						<img
							className={
								'myCard' +
								(this.state.highlightedCard === 0 ? ' highlight' : '')
							}
							src={
								myCard
									? '/assets/cards/' + cardToFilename(myCard) + '.svg'
									: '/assets/cards/blank.svg'
							}
						/>
					</div>
					<img
						className={
							'rightCard' +
							(this.state.highlightedCard === 3 ? ' highlight' : '')
						}
						src={
							rightCard
								? '/assets/cards/' + cardToFilename(rightCard) + '.svg'
								: '/assets/cards/blank.svg'
						}
					/>
				</div>
			</div>
		)
	}
}
