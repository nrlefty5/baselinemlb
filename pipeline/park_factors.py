# pipeline/park_factors.py
# Single source of truth for park-specific adjustment factors.
# All 30 MLB stadiums included.

PARK_K_FACTORS = {
    "Chase Field": 1, "Truist Park": 2, "Camden Yards": 0,
    "Fenway Park": -1, "Wrigley Field": -3, "Guaranteed Rate Field": 0,
    "Great American Ball Park": -2, "Progressive Field": 1,
    "Coors Field": -8, "Comerica Park": 2, "Minute Maid Park": 2,
    "Kauffman Stadium": 0, "Angel Stadium": 0, "Dodger Stadium": 4,
    "loanDepot park": 1, "American Family Field": -1,
    "Target Field": 0, "Citi Field": 1, "Yankee Stadium": 3,
    "Oakland Coliseum": 2, "Citizens Bank Park": -2, "PNC Park": 1,
    "Petco Park": 4, "Oracle Park": 5, "T-Mobile Park": 3,
    "Busch Stadium": 1, "Tropicana Field": 1, "Globe Life Field": 2,
    "Rogers Centre": 0, "Nationals Park": 1,
}

PARK_HR_FACTORS = {
    "Chase Field": 3, "Truist Park": 0, "Camden Yards": 2,
    "Fenway Park": 2, "Wrigley Field": 3, "Guaranteed Rate Field": 1,
    "Great American Ball Park": 5, "Progressive Field": 0,
    "Coors Field": 10, "Comerica Park": -2, "Minute Maid Park": 3,
    "Kauffman Stadium": 0, "Angel Stadium": 1, "Dodger Stadium": -1,
    "loanDepot park": -1, "American Family Field": 2,
    "Target Field": 1, "Citi Field": -1, "Yankee Stadium": 5,
    "Oakland Coliseum": -2, "Citizens Bank Park": 3, "PNC Park": -1,
    "Petco Park": -3, "Oracle Park": -4, "T-Mobile Park": 0,
    "Busch Stadium": 0, "Tropicana Field": 0, "Globe Life Field": 1,
    "Rogers Centre": 2, "Nationals Park": 1,
}
