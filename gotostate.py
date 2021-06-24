import argparse
import json

import boto3

client = boto3.client('stepfunctions')


def sm_arn_from_execution_arn(arn):
    """
    Get the State Machine Arn from the execution Arn
    Input: Execution Arn of a state machine
    Output: Arn of the state machine
    """
    sm_arn = arn.split(':')[:-1]
    sm_arn[5] = 'stateMachine'
    return ':'.join(sm_arn)


def parse_failure_history(failed_execution_arn):
    """
    Parses the execution history of a failed state machine to get the name of failed state and
    the input to the failed state
    Input failedExecutionArn - a string containing the execution Arn of a failed state machine
    Output - a list with two elements: [name of failed state, input to failed state]
    """

    failed_events = list()
    failed_at_parallel_state = False

    try:
        # Get the execution history
        response = client.get_execution_history(
            executionArn=failed_execution_arn,
            reverseOrder=True
        )
        next_token = response.get('nextToken')
        failed_events.extend(response['events'])
    except Exception as ex:
        raise ex

    while next_token is not None:
        try:
            # Get the execution history
            response = client.get_execution_history(
                executionArn=failed_execution_arn,
                reverseOrder=True,
                nextToken=next_token
            )
            next_token = response.get('nextToken')
            failed_events.extend(response['events'])
        except Exception as ex:
            raise ex

    # Confirm that the execution actually failed, raise exception if it didn't fail
    try:
        failed_events[0]['executionFailedEventDetails']
    except Exception as cause:
        raise Exception('Execution did not fail', cause)
    '''
    If we have a 'States.Runtime' error (for example if a task state in our state
    machine attempts to execute a lambda function in a different region than the
    state machine, get the id of the failed state, use id of the failed state to
    determine failed state name and input
    '''
    if failed_events[0]['executionFailedEventDetails']['error'] == 'States.Runtime':
        failed_id = int(filter(str.isdigit, str(failed_events[0]['executionFailedEventDetails']['cause'].split()[13])))
        failed_state = failed_events[-1 * failed_id]['stateEnteredEventDetails']['name']
        failed_input = failed_events[-1 * failed_id]['stateEnteredEventDetails']['input']
        return failed_state, failed_input
    '''
    We need to loop through the execution history, tracing back the executed steps
    The first state we encounter will be the failed state
    If we failed on a parallel state, we need the name of the parallel state rather than the
    name of a state within a parallel state it failed on. This is because we can only attach
    the goToState to the parallel state, but not a sub-state within the parallel state.
    This loop starts with the id of the latest event and uses the previous event id's to trace
    back the execution to the beginning (id 0). However, it will return as soon it finds the name
    of the failed state
    '''
    current_event_id = failed_events[0]['id']
    while current_event_id != 0:
        # multiply event id by -1 for indexing because we're looking at the reversed history
        current_event = failed_events[-1 * current_event_id]
        '''
        We can determine if the failed state was a parallel state because it an event
        with 'type'='ParallelStateFailed' will appear in the execution history before
        the name of the failed state
        '''
        if current_event['type'] == 'ParallelStateFailed':
            failed_at_parallel_state = True
        '''
        If the failed state is not a parallel state, then the name of failed state to return
        will be the name of the state in the first 'TaskStateEntered' event type we run into
        when tracing back the execution history
        '''
        if current_event['type'] == 'TaskStateEntered' and not failed_at_parallel_state:
            failed_state = current_event['stateEnteredEventDetails']['name']
            failed_input = current_event['stateEnteredEventDetails']['input']
            return failed_state, failed_input
        '''
        If the failed state was a parallel state, then we need to trace execution back to
        the first event with 'type'='ParallelStateEntered', and return the name of the state
        '''
        if current_event['type'] == 'ParallelStateEntered' and failed_at_parallel_state:
            failed_state = current_event['stateEnteredEventDetails']['name']
            failed_input = current_event['stateEnteredEventDetails']['input']
            return failed_state, failed_input
        # Update the id for the next execution of the loop
        current_event_id = current_event['previousEventId']


def attach_go_to_state(failed_state_name, state_machine_arn):
    """
    Given a state machine arn and the name of a state in that state machine, create a new state machine
    that starts at a new choice state called the 'GoToState'. The "GoToState" will branch to the named
    state, and send the input of the state machine to that state, when a variable called "resuming" is
    set to True
    Input   failedStateName - string with the name of the failed state
            stateMachineArn - string with the Arn of the state machine
    Output  response from the create_state_machine call, which is the API call that creates a new state machine
    """
    try:
        response = client.describe_state_machine(
            stateMachineArn=state_machine_arn
        )
    except Exception as cause:
        raise Exception('Could not get ASL definition of state machine', cause)
    role_arn = response['roleArn']
    state_machine = json.loads(response['definition'])
    # Create a name for the new state machine
    new_name = response['name'] + '-with-GoToState'
    # Get the StartAt state for the original state machine, because we will point the 'GoToState' to this state
    original_start_at = state_machine['StartAt']
    '''
    Create the GoToState with the variable $.resuming
    If new state machine is executed with $.resuming = True, then the state machine will skip to the failed state
    Otherwise, it will execute the state machine from the original start state
    '''
    go_to_state = {
        'Type': 'Choice',
        'Choices': [{'Variable': '$.resuming', 'BooleanEquals': False, 'Next': original_start_at}],
        'Default': failed_state_name
    }
    # Add GoToState to the set of states in the new state machine
    state_machine['States']['GoToState'] = go_to_state
    # Add StartAt
    state_machine['StartAt'] = 'GoToState'
    # Create new state machine
    try:
        response = client.create_state_machine(
            name=new_name,
            definition=json.dumps(state_machine),
            roleArn=role_arn
        )
    except Exception as cause:
        raise Exception('Failed to create new state machine with GoToState', cause)
    return response


if __name__ == '__main__':
    '''
    Main
    Run as:
    python gotostate.py --failedExecutionArn '<Failed_Execution_Arn>'"
    '''
    parser = argparse.ArgumentParser(description='Execution Arn of the failed state machine.')
    parser.add_argument('--failedExecutionArn', dest='failedExecutionArn', type=str)
    args = parser.parse_args()
    failed_sm_state, failed_sm_info = parse_failure_history(args.failedExecutionArn)
    failed_sm_arn = sm_arn_from_execution_arn(args.failedExecutionArn)
    new_machine = attach_go_to_state(failed_sm_state, failed_sm_arn)
    print("New State Machine Arn: {}".format(new_machine['stateMachineArn']))
    print("Execution had failed at state: {} with Input: {}".format(failed_sm_state, failed_sm_info))
