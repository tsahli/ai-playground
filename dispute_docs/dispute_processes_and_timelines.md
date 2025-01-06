# Dispute Process and Timelines

## Process Overview

1. Dispute received from issuer (120-540 days from transaction)
2. Response phase - accept, challenge, or ignore
3. Issuer review (up to 55 days)
4. Final outcome or arbitration

## Response Timelines

| Network          | Evidence Due | Info Request |
| ---------------- | ------------ | ------------ |
| Visa             | 20 days      | Optional     |
| Mastercard       | 20 days      | Optional     |
| Amex             | 10 days      | 20 days      |
| Diners/Discover  | 20 days      | -            |
| JCB              | 20 days      | -            |
| Cartes Bancaires | 20 days      | -            |

_Third-party acquirers (Mashreq/Worldpay): 10 days_

## Status Flow

### Initial

- evidence_required: New dispute
- resolved: Auto-defended (prior refund)
- canceled: Issuer withdrawal

### Response

- evidence_under_review: Evidence submitted
- accepted: Merchant accepts
- expired: No response

### Final

- won: Evidence accepted
- lost: Evidence rejected
- arbitration_under_review: In appeal

## Arbitration Guidelines

- Must escalate within 10 days (5 for Visa allocation)
- Consider costs and timeline
- Additional evidence allowed except Visa fraud/auth
- Submit via API or contact Disputes Team

## Info Requests (Retrieval Requests)

- Precede formal disputes
- No funds withdrawn
- Quick response recommended
- Required for Amex (20 days)
