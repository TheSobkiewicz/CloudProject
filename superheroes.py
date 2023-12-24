#!/usr/bin/env python
import logging
import os
from json import dumps
from textwrap import dedent
from typing import cast

import neo4j
from flask import Flask, Response, request
from neo4j import GraphDatabase, basic_auth
from typing_extensions import LiteralString

app = Flask(__name__, static_url_path="/static/")

url = os.getenv("NEO4J_URI", "url")
username = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "password")
neo4j_version = os.getenv("NEO4J_VERSION", "5")
database = os.getenv("NEO4J_DATABASE", "neo4j")

port = int(os.getenv("PORT", 8080))

driver = GraphDatabase.driver(url, auth=basic_auth(username, password))


def query(q: LiteralString) -> LiteralString:
    return cast(LiteralString, dedent(q).strip())


@app.route("/")
def get_index():
    return app.send_static_file("index.html")

def serialize_character(character):
    return {
        "name": character["name"],
        "alias": character["alias"],
        "type": character["type"]
    }

def serialize_company(company):
    return {
        "name": company["name"],
        "type": "COMPANY"
    }

def serialize_universe(universe):
    return {
        "name": universe["name"],
        "type": "UNIVERSE"
    }

def serialize_team(team):
    return {
        "name": team["name"],
        "type":  "GOOD" if team["is_Good"] else "BAD"
    }



@app.route("/graph")
def get_teams_graph():
    records, _, _ = driver.execute_query(
        query("""
            MATCH (m:TEAM)
            OPTIONAL MATCH (m)<-[:part_of]-(a:HERO)
            OPTIONAL MATCH (m)<-[:part_of]-(v:VILLAIN)
            WITH m, collect(DISTINCT { alias: a.Alias, name: a.Name, type: 'HERO' }) as heroes, collect(DISTINCT { alias: v.Alias, name: v.Name, type: 'VILLAIN' }) as villains
            RETURN { name: m.Name, is_Good: m.isGood } as parent, heroes + villains as children
            LIMIT $limit
        """),
        database_=database,
        routing_="r",
        limit=request.args.get("limit", 500)
    )
    return process_graph(records, serialize_team, serialize_character)


@app.route("/graph/enemies")
def get_enemies_graph():
    records, _, _ = driver.execute_query(
        query("""
            MATCH (t:TEAM) - [:enemies] -> (t2:TEAM)
            return { name: t.Name, is_Good: t.isGood } as parent, collect(DISTINCT { name: t2.Name, is_Good: t2.isGood }) as children
            LIMIT $limit
        """),
        database_=database,
        routing_="r",
        limit=request.args.get("limit", 500)
    )
    return process_graph(records, serialize_team, serialize_team)


@app.route("/graph/universes")
def get_universes_graph():
    records, _, _ = driver.execute_query(
        query("""
            MATCH (t:TEAM) - [:part_of] -> (u:UNIVERSE)
            return { name: t.Name, is_Good: t.isGood } as parent, collect(DISTINCT { name: u.Name }) as children
            LIMIT $limit
        """),
        database_=database,
        routing_="r",
        limit=request.args.get("limit", 500)
    )
    return process_graph(records, serialize_team, serialize_universe)


@app.route("/graph/companies")
def get_companies_graph():
    records, _, _ = driver.execute_query(
        query("""
            match (o: OWNER) - [:owns] -> (u:UNIVERSE)
            return { name: o.Name } as parent, collect(DISTINCT { name: u.Name }) as children
        """),
        database_=database,
        routing_="r",
        limit=request.args.get("limit", 500)
    )
    return process_graph(records, serialize_company, serialize_universe)


@app.route("/graph/bad_in_good")
def get_bad_in_good_graph():
    records, _, _ = driver.execute_query(
        query("""
              MATCH (t:TEAM) <- [:part_of] - (h:HERO)
              where not t.isGood
            return { name: t.Name, is_Good: t.isGood } as parent, collect ({ name: h.Name, alias: h.Alias, type: 'HERO' }) as children
    """),
        database_=database,
        routing_="r",
        limit=request.args.get("limit", 500)
    )
    return process_graph(records, serialize_team, serialize_character)


def process_graph(records, parent_processing_function, child_processing_function):
    nodes = []
    rels = []
    i = 0
    for record in records:
        nodes.append(parent_processing_function(record["parent"]))
        target = i
        i += 1
        for person in [member for member in record["children"] if member["name"] != None]:
            person = child_processing_function(person)
            try:
                source = nodes.index(person)
            except ValueError:
                nodes.append(person)
                source = i
                i += 1
            rels.append({"source": source, "target": target})
    return Response(dumps({"nodes": nodes, "links": rels}),
                    mimetype="application/json")


if __name__ == "__main__":
    logging.root.setLevel(logging.INFO)
    logging.info("Starting on port %d, database is at %s", port, url)
    try:
        app.run(port=port)
    finally:
        driver.close()
