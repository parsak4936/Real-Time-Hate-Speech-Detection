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
* `backup data/` - backup file in case of not losing the original data sets

## Setup & Installation

### Prerequisites
* Docker Desktop (Running)
* Python 3.9+

### Download Data & Models
1. Download the project assets here: **[Hate-detection-datasets](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQALdCPwnEgERaCJu7DbUNOTAfZ656fGZeJzMy4RAtntCXI?e=yLHFRa)**
2. Extract the contents:
   * Place the models on the project folder. **[models](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQCbk51AuA3DQoF0l4almQK4AQW3uwICBwxVIqRSceczPec?e=bBY8vE)**

### Infrastructure Setup (Docker)
This project relies on a containerized environment to run services namely Kafka, Zookeeper, Spark, Elasticsearch, and Kibana.

### 1. Install Docker
Ensure Docker Desktop is installed and running on the machine.
* **Windows/Mac/Linux:** Download from [Docker Desktop](https://www.docker.com/products/docker-desktop/).

### 2. Start the Environment
Navigate to the project root directory (where `docker-compose.yml` is located) and run the following command to download images and start the containers in detached mode:

```bash
docker-compose up -d