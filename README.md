# aws-sfn-resume-from-any-state
Resume failed state machines midstream and skip all previously succeded steps. 

This repository contains the CloudFormation template and code to support the [Resume AWS Step Functions from Any State](ADD LINK HERE) blog post.

The repository contains the following files:

- "gotostate.py" - the script that creates a state machine that is able to resume execution of a failed state machine, from the point of failure.

- "sample_execution_history" - an example execution history of a failed state machine, which the scipt parses in order to help resume workflows midstream.  

- "ResumeFromState.yaml" -  a CloudFormation template that sets up a State Machine and Lambda functions to demonstrate this example.


## Tutorial

The ResumeFromState.yaml CloudFormation template creates a State Machine and Lambda functions to illustrate how to use the 'gotostate.py' script in order to resume a state machine that has failed midstream. 

To run this example, first use the CloudFormation template provided to create the sample State Machine and Lambda Functions. 

In the AWS Step Function console, select the State Machine with "ResumeFromStateExample" in its title. 

Run the state machine with the following input:

```
{
    "Message":"Your message here"
}
``` 

This input will cause the state machine to execute the first parallel state then fail, because the next step expects an input variable called "foo" in the JSON.

Let's use the 'gotostate.py' to resume this State Machine from the step it failed at - skipping states that had sucesfully been completed. 

Run the script with the following command:

```
python gotostate.py --failedExecutionArn '<EXECUTION_ARN_OF_FAILED_STATE_MACHINE>'
```

This creates a new state machine with "-with-GoToState" appended to the title of the original state machine. The script also outputs the input that caused the state machine to fail with it was originally run. 

Let's execute the new State Machine, adding the "foo" input variable that our workflow was expecting. We also need to set "resuming":true, so we can tell the new State Machine to branch to the failed state, and skip the states that had already succeeded.

```
{
  "foo": 1,
  "output": [
    {
      "Message": "Hello!"
    },
    {
      "Message": "Hello!"
    }
  ],
  "resuming": true
}
```

Run the new State Machine with the input above, and notice that it resumes from the failed states and completes execution sucessfully. 
