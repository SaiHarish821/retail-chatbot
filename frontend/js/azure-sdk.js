import { CallClient } from '@azure/communication-calling';
import { AzureCommunicationTokenCredential } from '@azure/communication-common';

window.Azure = {
  Communication: {
    Calling: { CallClient },
    Common: { AzureCommunicationTokenCredential }
  }
};
