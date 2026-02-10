# Real-Time Hate Speech Detection

**Big Data Management's Project - Parsa Kazemi**

**University of Messina**



## Project Overview

This project implements a scalable, real-time pipeline for detecting hate and offensive speech in live social media streams (X, YouTube, Twitch, and Reddit). It utilizes a DistilBERT model (Accuracy: 80.2%) trained on a consolidated dataset of ~53k samples (Davidson, HateXplain, ToxiGen).



# original link for data sets :

* **Davidson et al. (2017):** Automated Hate Speech Detection and the Problem of Offensive Language.

    * [Source Repository](https://github.com/t-davidson/hate-speech-and-offensive-language)

* **HateXplain:** A Benchmark Dataset for Explainable Hate Speech Detection.

    * [Source Repository](https://github.com/hate-alert/HateXplain)

* **ToxiGen:** A Large-Scale Machine-Generated Dataset for Adversarial and Implicit Hate Speech Detection.

    * [Hugging Face Dataset](https://huggingface.co/datasets/toxigen/toxigen-data)



## Repository Structure

* `src/` - Source code for Producers and the AI Processor.

* `data/` - files which the code will read and analyze from.

* `docker-compose.yml` - Infrastructure (Kafka, Zookeeper, Spark, Elasticsearch, Kibana).

* `models/` - pre-trained models in result for faster test on newer data.

* `requirements.txt` - Python dependency list.



## Setup and Installation



### Prerequisites

* Docker Desktop installed and running.

* Python 3.9 or higher installed on your system.



### Download  Assets

* **Datasets:** [Download Link](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQALdCPwnEgERaCJu7DbUNOTAfZ656fGZeJzMy4RAtntCXI?e=yLHFRa)

    * Action: Extract the CSV files into the data folder.

* **Model:** [Download Link](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQCbk51AuA3DQoF0l4almQK4AQW3uwICBwxVIqRSceczPec?e=bBY8vE)

    * Action: Extract the bert_final folder into the models folder.



## Infrastructure Setup (Docker)

Navigate to the project root directory where docker-compose.yml is located and run:



docker-compose up -d


### Python Application Setup

1. **Install Dependencies:** |   pip install -r requirements.txt  |

2. **Start the  Engine:** Open Terminal #1: |  python src/processor.py  |

3. **Start a Data Stream:** Open Terminal #2 and #3 : |  python src/tweet_producer.py  |  and  |  python src/youtube_producer.py   |



* you can have as many as youtube instancs with different links of youtube stream, if there is no link, there is a default link into it.




### Import the Dashboard

To see the pre-configured charts, you must import the dashboard file:

1. Open Kibana: [http://localhost:5601](http://localhost:5601)

2. Go to **Stack Management** -> **Saved Objects**.

3. Click **Import** (top right corner).

4. Select the file named `dashboard.ndjson` located in this repository.

5. Click **Import**.

6. Go back to **Dashboard** and open the new "Real-Time Analysis" dashboard.

