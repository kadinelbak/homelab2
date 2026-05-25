import React, { Component } from 'react'
import { Logo, Button, BackButton } from './Components'
import Socket from './sockets'

export default class JoinPage extends Component {
	constructor(props) {
		super(props)

		const bundle = props.location.state

		this.state = {
			roomId: '',
			id: bundle.id
		}

		Socket.on('updatePlayers', players => {
			this.props.history.push('/lobby', {
				roomId: this.state.roomId,
				id: this.state.id,
				players
			})
		})
	}

	handleRoomIdChange = e => {
		this.setState({ roomId: e.target.value })
	}

	handleJoinRoom = () => {
		Socket.emit('joinRoom', this.state.roomId)
	}

	handleBackClick = () => {
		window.location.href = '/'
	}

	render() {
		return (
			<div className="wrapper">
				<div className="center">
					<h1>room code</h1>
					<input
						placeholder="type it here :)"
						onChange={this.handleRoomIdChange}
					/>
					<div className="buttonWrapper">
						<Button
							enabled={this.state.roomId.match(/\b[0-9a-f]{6}\b/g)}
							text="join room"
							onClick={this.handleJoinRoom}
						/>
					</div>
				</div>
				<BackButton onClick={this.handleBackClick} />
				<Logo />
			</div>
		)
	}
}
