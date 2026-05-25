import React from 'react'
import { BrowserRouter as Router, Route, Switch } from 'react-router-dom'
import MenuPage from './MenuPage'
import JoinPage from './JoinPage'
import LobbyPage from './LobbyPage'
import GamePage from './GamePage'

export default class App extends React.Component {
	render() {
		return (
			<Router>
				<Switch>
					<Route exact path="/" component={MenuPage} />
					<Route exact path="/join" component={JoinPage} />
					<Route exact path="/lobby" component={LobbyPage} />
					<Route exact path="/game" component={GamePage} />
				</Switch>
			</Router>
		)
	}
}
