from apps.core.exceptions import BusinessOSException


class ApprovalsException(BusinessOSException):
    default_message = "An approvals engine error occurred."
    default_code = "approvals_error"


class ApprovalRuleNotFoundError(ApprovalsException):
    default_message = "The requested approval rule does not exist."
    default_code = "approval_rule_not_found"


class ApprovalRequestNotFoundError(ApprovalsException):
    default_message = "The requested approval request does not exist."
    default_code = "approval_request_not_found"


class InvalidApprovalStateError(ApprovalsException):
    default_message = "The approval request is not in a valid state for this action."
    default_code = "invalid_approval_state"


class UnauthorizedApproverError(ApprovalsException):
    default_message = "You are not authorized to decide this approval request."
    default_code = "unauthorized_approver"


class ApprovalRuleValidationError(ApprovalsException):
    default_message = "Approval rule parameters are invalid."
    default_code = "approval_rule_validation_error"
