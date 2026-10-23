"""Role-registration semantics; no trained-model claim is implied."""
import unittest
from roster import CONTRACTS, ROLES, PAIRS
from readiness import audit, require_classifier
from lab import ACTORS, Bus
from admin import ROLES as ALL_ROLES

class Roster(unittest.TestCase):
    def test_pairs_and_total(self):
        self.assertEqual(len(PAIRS), 16)
        self.assertEqual(len(CONTRACTS), 50)
        self.assertEqual(len(ALL_ROLES), 66)
        self.assertEqual(len({row[0] for row in ALL_ROLES}), 66)
        for role, contract in CONTRACTS.items():
            if contract['counterpart'] is not None:
                self.assertEqual(CONTRACTS[contract['counterpart']]['counterpart'], role)
            self.assertIn(role, ACTORS)
            self.assertFalse(contract['independent_weights'])
            self.assertEqual(contract['shared_modes'],['observe','analyze','plan','verify'])

    def test_untrained_roles_fail_closed(self):
        states = audit()
        self.assertEqual(len(states), len(ALL_ROLES))
        for role in CONTRACTS:
            self.assertFalse(states[role]['classifier_enabled'])
            with self.assertRaises(ValueError):
                require_classifier(role)

if __name__ == '__main__':
    unittest.main()
