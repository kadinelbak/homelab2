import React, { Component } from 'react'

export default class Card extends Component {
	render() {
		if (this.props.flip) {
			return <img className="card" src={'/assets/cards/cardback.svg'} />
		}
		const suit = (n => {
			switch (n) {
				case 0:
					return 'h'
				case 1:
					return 's'
				case 2:
					return 'c'
				case 3:
					return 'd'
				default:
					return 'c'
			}
		})(this.props.suit)
		const number =
			this.props.number < 10
				? '0' + this.props.number
				: this.props.number.toString()
		return (
			<img
				onClick={this.props.onClick}
				className="card"
				src={'/assets/cards/' + suit + number + '.svg'}
			/>
		)
	}
}
