const CardSuit = Object.freeze({
  HEARTS: 0,
  SPADES: 1,
  CLUBS: 2,
  DIAMONDS: 3
})

class Card {
  constructor(suit, number) {
    this.suit = suit
    this.number = number
  }

  getNumberName() {
    switch (this.number) {
      case 1:
        return 'Ace'
      case 11:
        return 'Jack'
      case 12:
        return 'Queen'
      case 13:
        return 'King'
      default:
        return this.number
    }
  }

  getPoints() {
    if (this.number === 12 && this.suit === CardSuit.SPADES) return 13
    if (this.suit === CardSuit.HEARTS) return 1
    return 0
  }

  getSuitName() {
    switch (this.suit) {
      case CardSuit.SPADES:
        return 'Spades'
      case CardSuit.HEARTS:
        return 'Hearts'
      case CardSuit.CLUBS:
        return 'Clubs'
      case CardSuit.DIAMONDS:
        return 'Diamonds'
    }
  }

  toString() {
    return this.getNumberName() + ' of ' + this.getSuitName()
  }
}

class Deck {
  constructor() {
    var cards = []

    for (var number = 1; number <= 13; number++) {
      cards.push(new Card(CardSuit.SPADES, number))
      cards.push(new Card(CardSuit.HEARTS, number))
      cards.push(new Card(CardSuit.CLUBS, number))
      cards.push(new Card(CardSuit.DIAMONDS, number))
    }

    this.cards = cards

    this.shuffle()
  }

  shuffle() {
    var a = this.cards
    for (var i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[a[i], a[j]] = [a[j], a[i]]
    }
  }

  deal() {
    const hands = [
      new Hand(this.cards.slice(0, 13)),
      new Hand(this.cards.slice(13, 26)),
      new Hand(this.cards.slice(26, 39)),
      new Hand(this.cards.slice(39, 52))
    ]

    hands.forEach(h => h.sort())

    return hands
  }
}

class Hand {
  constructor(cards) {
    this.cards = cards
  }

  sort() {
    this.cards.sort(
      (a, b) =>
        (b.suit - a.suit) * 100 +
        ((b.number === 1 ? 14 : b.number) - (a.number === 1 ? 14 : a.number))
    )
  }

  remove(suit, number) {
    for (let i = 0; i < this.cards.length; i++) {
      const card = this.cards[i]

      if (card.suit === suit && card.number === number) {
        return this.cards.splice(i, 1)[0]
      }
    }
  }

  add(suit, number, sort = true) {
    this.cards.push(new Card(suit, number))

    if (sort) this.sort()
  }
}

const evaluateTrick = cards => {
  // the suit of the trick is the suit of the first card played
  const suit = cards[0].suit

  var points = 0
  var highestNumOfSuit = 0
  var highestNumIndex = -1

  for (let i = 0; i < cards.length; i++) {
    const card = cards[i]
    // add to points
    points += card.getPoints()

    if (card.suit !== suit) continue

    let weightedNumber = card.number
    if (weightedNumber === 1) weightedNumber = 14

    if (weightedNumber > highestNumOfSuit) {
      highestNumOfSuit = weightedNumber
      highestNumIndex = i
    }
  }

  return {
    taker: highestNumIndex,
    points
  }
}

module.exports = {
  CardSuit,
  Card,
  Deck,
  evaluateTrick
}
