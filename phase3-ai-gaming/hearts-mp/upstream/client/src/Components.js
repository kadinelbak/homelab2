import React, { Component } from 'react'

export class Logo extends Component {
	render() {
		return <h2 className="logo">hearts</h2>
	}
}

export class Button extends Component {
	render() {
		return (
			<div
				style={this.props.style}
				onClick={() => {
					if (this.props.enabled) {
						this.props.onClick()
					}
				}}
				className={'button' + (this.props.enabled ? '' : ' disabled')}>
				{this.props.text}
			</div>
		)
	}
}

export class BackButton extends Component {
	render() {
		return (
			<a
				className="textButton"
				style={{ position: 'absolute', top: '1em', left: '3em' }}
				onClick={this.props.onClick}>
				<h2>back</h2>
			</a>
		)
	}
}
