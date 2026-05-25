import React, { Component } from 'react'
import { Logo, Button } from './Components'
import Socket from './sockets'

export default class LobbyPage extends Component {
	constructor(props) {
		super(props)

		const bundle = props.location.state

		this.state = {
			roomId: bundle.roomId,
			id: bundle.id,
			players: bundle.players,
			voted: false
		}

		Socket.on('updatePlayers', players => {
			this.setState({ players })
		})

		Socket.on('startGame', hand => {
			this.props.history.push('/game', {
				roomId: this.state.roomId,
				id: this.state.id,
				players: this.state.players,
				hand: hand.cards
			})
		})
	}

	handleVoteStart = () => {
		this.setState({ voted: true })
		Socket.emit('voteStart')
	}

	leaveRoom = () => {
		Socket.emit('leaveRoom')
		window.location.href = '/'
	}

	render() {
		return (
			<div className="wrapper">
				<div className="center">
					<h1>{'lobby: ' + this.state.roomId}</h1>
					<div className="nameWrapper">
						{this.state.players.map(p => {
							var cN = ''
							if (p.id === this.state.id) cN += 'me '
							if (p.voted) cN += 'ready'
							return (
								<h2 key={p.id} className={cN}>
									{p.name}
								</h2>
							)
						})}
					</div>
					<div className="buttonWrapper">
						<Button
							enabled={!this.state.voted}
							text="i'm ready"
							onClick={this.handleVoteStart}
						/>
					</div>
				</div>
				<Logo />
				<Button
					enabled={true}
					style={{ position: 'absolute', top: '1em', right: '1em' }}
					text="leave room"
					onClick={this.leaveRoom}
				/>
			</div>
		)
	}
}
